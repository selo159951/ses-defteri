"""First-start download: progress, resume, retry, no internet, nothing missing. Never touches the network or the
real %APPDATA%: SESDEFTERIBASIT_HOME and the model dir point into a temp folder and urlopen is faked."""
import socket
import urllib.error

import pytest

from backend import models

SIZES = {"config.json": 10, "preprocessor_config.json": 5, "tokenizer.json": 20, "vocabulary.json": 15, "model.bin": 1000}
GGML_SIZE = 400


def content_for(name: str) -> bytes:
    return (name.encode() * 2000)[: SIZES.get(name, GGML_SIZE)]


class FakeResp:
    def __init__(self, data: bytes, status=200, chunk=100):
        self._d, self.status, self._i, self._c = data, status, 0, chunk
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        out = self._d[self._i:self._i + min(n, self._c)]
        self._i += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """Replacement for urlopen: serves content_for(file) honouring Range; can fail or cut a body short."""

    def __init__(self):
        self.calls = []  # (file name, Range header)
        self.fail = []  # exceptions raised by the next calls, one per call
        self.cut_after = None  # {file: bytes} body ends early (connection cut)
        self.ignore_range = False

    def __call__(self, req, timeout=0):
        name = req.full_url.rsplit("/", 1)[1]
        rng = req.headers.get("Range")
        self.calls.append((name, rng))
        if self.fail:
            raise self.fail.pop(0)
        data = content_for(name)
        status = 200
        if rng and not self.ignore_range:
            data = data[int(rng.split("=")[1].rstrip("-")):]
            status = 206
        if self.cut_after and name in self.cut_after:
            cut = self.cut_after.pop(name)
            r = FakeResp(data[:cut], status)
            r.headers["Content-Length"] = str(len(data))  # promised more than it delivers
            return r
        return FakeResp(data, status)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SESDEFTERI_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("SESDEFTERIBASIT_NO_BUNDLED", "1")
    monkeypatch.setattr(models, "CT2_FILES", {"large-v3-turbo": [(f, n) for f, n in SIZES.items()]})
    monkeypatch.setitem(models.GGML, "large-v3-turbo-q5_0", {"size": GGML_SIZE})
    net = FakeNet()
    monkeypatch.setattr(models, "_urlopen", net)
    sleeps = []
    monkeypatch.setattr(models, "_sleep", sleeps.append)
    monkeypatch.setattr(models, "_fr", {"state": "idle", "error": None, "kind": None, "retrying": False, "attempt": 0,
                                        "live": {}, "samples": models.deque(), "thread": None})
    net.sleeps = sleeps
    return net


def test_nothing_missing_means_no_download(env):
    for f in SIZES:
        (models.ct2_dir() / f).parent.mkdir(parents=True, exist_ok=True)
        (models.ct2_dir() / f).write_bytes(content_for(f))
    models.ggml_dir().mkdir(parents=True, exist_ok=True)
    (models.ggml_dir() / "ggml-large-v3-turbo-q5_0.bin").write_bytes(b"x" * GGML_SIZE)
    st = models.start_first_run_download()
    assert st["needed"] is False and st["state"] == "done"
    assert env.calls == []
    assert models.is_downloaded("large-v3-turbo") and models.bundled() == models.ct2_dir()
    assert models.ggml_path("large-v3-turbo-q5_0").name == "ggml-large-v3-turbo-q5_0.bin"
    assert models.ggml_path("large-v3-turbo") is None
    assert models.first_run_blocking() is False


def test_full_download_progress_and_result(env):
    st0 = models.first_run_status()
    assert st0["needed"] and st0["state"] == "idle" and st0["done"] == 0
    assert st0["total"] == sum(SIZES.values()) + GGML_SIZE
    assert not models.is_downloaded("large-v3-turbo")
    st = models.ensure(wait=True)
    assert st["state"] == "done" and st["needed"] is False and st["done"] == st["total"]
    assert [i["complete"] for i in st["items"]] == [True, True]
    assert models.is_downloaded("large-v3-turbo")
    assert models.ggml_path("large-v3-turbo-q5_0").stat().st_size == GGML_SIZE
    assert (models.ct2_dir() / "model.bin").read_bytes() == content_for("model.bin")
    assert not list(models.root().rglob("*.incomplete"))


def test_progress_numbers_while_running(env, monkeypatch):
    t = [100.0]
    monkeypatch.setattr(models, "_now", lambda: t[0])
    path = models.ct2_dir() / "model.bin"
    models._fr.update(state="downloading")
    for i in range(1, 6):  # 100 bytes per second
        t[0] += 1.0
        models._record(path, i * 100)
    st = models.first_run_status()
    assert st["state"] == "downloading" and st["done"] == 500
    assert st["speed"] == 100
    assert st["eta"] == round((st["total"] - 500) / 100)
    t[0] += 10  # nothing arrived for a while: speed unknown again
    assert models.first_run_status()["speed"] == 0 and models.first_run_status()["eta"] is None


def test_resume_from_partial_file(env):
    part = models.ct2_dir() / "model.bin.incomplete"
    part.parent.mkdir(parents=True)
    part.write_bytes(content_for("model.bin")[:600])
    st = models.first_run_status()
    assert st["done"] == 600  # counted before anything starts
    models.ensure(wait=True)
    assert ("model.bin", "bytes=600-") in env.calls
    assert (models.ct2_dir() / "model.bin").read_bytes() == content_for("model.bin")  # not corrupted


def test_server_ignoring_range_restarts_cleanly(env):
    part = models.ct2_dir() / "model.bin.incomplete"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"junk" * 50)
    env.ignore_range = True
    models.ensure(wait=True)
    assert (models.ct2_dir() / "model.bin").read_bytes() == content_for("model.bin")


def test_retry_after_cut_connection_continues(env):
    env.cut_after = {"model.bin": 300}
    st = models.ensure(wait=True)
    assert st["state"] == "done"
    ranges = [r for n, r in env.calls if n == "model.bin"]
    assert ranges[0] is None and ranges[1] == "bytes=300-"
    assert env.sleeps == [models.RETRY_DELAYS[0]]
    assert (models.ct2_dir() / "model.bin").read_bytes() == content_for("model.bin")


def test_no_internet_after_retries(env):
    env.fail = [urllib.error.URLError(socket.gaierror("no host")) for _ in range(10)]
    st = models.ensure(wait=True)
    assert st["state"] == "no_internet" and st["kind"] == "no_internet"
    assert "İnternete bağlanılamadı" in st["error"] and "Tekrar dene" in st["error"]
    assert len(env.calls) == len(models.RETRY_DELAYS) + 1 and env.sleeps == list(models.RETRY_DELAYS)
    assert models.first_run_blocking() is True
    env.fail = []  # "Tekrar dene": the next start works once the network is back
    st = models.ensure(wait=True)
    assert st["state"] == "done"


def test_http_error_is_a_plain_error(env):
    err = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    env.fail = [err, err, err]
    st = models.ensure(wait=True)
    assert st["state"] == "error" and "bir sorun oldu" in st["error"]


def test_not_enough_disk_space(env, monkeypatch):
    class U:
        free = 10

    monkeypatch.setattr(models.shutil, "disk_usage", lambda p: U)
    st = models.ensure(wait=True)
    assert st["state"] == "error" and st["kind"] == "disk" and "boş yer" in st["error"]
    assert env.calls == []


def test_complete_folder_found_by_bundled_means_no_download(env, tmp_path, monkeypatch):
    d = tmp_path / "shipped"
    d.mkdir()
    for f in SIZES:
        (d / f).write_bytes(b"x")
    monkeypatch.setattr(models, "ct2_dir", lambda name="large-v3-turbo": d)
    assert models.bundled() == d and models.is_downloaded("large-v3-turbo")
