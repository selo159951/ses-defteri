"""Backup and restore of the data folder (SESDEFTERI_HOME points at a tmp dir)."""
import json
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import backup, bridge, store, version  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def fresh_status():
    backup._set(busy=False, kind="", path="", error="", done=False, files=0, result=None)


def wait_done(status):
    for _ in range(300):  # 15 s at most, the zips here are tiny
        st = status()
        if not st["busy"] and (st["done"] or st["error"]):
            return st
        time.sleep(0.05)
    return status()


def fill_data():
    """A data folder with one job and everything that must or must not end up in a backup."""
    root = store.data_dir()
    jid = store.create_job("toplanti.wav")
    store.update_job(jid, status="done", starred=True, tags=["is"])
    (store.job_path(jid) / "audio.mp3").write_bytes(b"mp3")
    (store.job_path(jid) / "gecici.part").write_bytes(b"x")
    (root / "settings.json").write_text("{}", "utf-8")
    (root / "models").mkdir()
    (root / "models" / "big.bin").write_bytes(b"m")
    (root / "webview").mkdir()
    (root / "webview" / "cache.bin").write_bytes(b"w")
    (root / "llm").mkdir()
    (root / "llm" / "x.bin").write_bytes(b"l")
    live = root / "recordings" / "20260101-120000"  # still being written
    live.mkdir(parents=True)
    (live / "meta.json").write_text(json.dumps({"state": "recording", "title": "şimdi"}), "utf-8")
    (live / "system.pcm").write_bytes(b"p")
    mixed = root / "recordings" / "20250101-120000"  # a leftover from a crash: worth keeping
    mixed.mkdir(parents=True)
    (mixed / "meta.json").write_text(json.dumps({"state": "mixed", "wav": "top.wav"}), "utf-8")
    (mixed / "top.wav").write_bytes(b"wav")
    (root / "yarim.part").write_bytes(b"x")
    (root / "iz.log").write_bytes(b"x")
    return root, jid


def names(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return set(z.namelist())


# ---------------------------------------------------------------- create
def test_create_zips_the_data_folder_but_not_the_bulky_things(tmp_path):
    root, jid = fill_data()
    out = tmp_path / "yedek.zip"
    r = backup.create(out)
    assert r["files"] > 0 and r["bytes"] > 0 and out.exists()
    n = names(out)
    assert f"jobs/{jid}/transcript.json" in n and f"jobs/{jid}/audio.mp3" in n
    assert "settings.json" in n and "manifest.json" in n
    assert "recordings/20250101-120000/top.wav" in n          # a finished leftover is kept
    assert not any(x.startswith(("models/", "webview/", "llm/")) for x in n)
    assert not any(x.startswith("recordings/20260101") for x in n)  # a recording in progress is not
    assert not any(x.endswith((".part", ".log")) for x in n)


def test_create_appends_zip_suffix(tmp_path):
    fill_data()
    out = backup.create(tmp_path / "yedek")
    assert out["path"].endswith(".zip") and Path(out["path"]).exists()


def test_manifest_fields(tmp_path):
    fill_data()
    out = tmp_path / "y.zip"
    backup.create(out)
    with zipfile.ZipFile(out) as z:
        m = json.loads(z.read("manifest.json").decode("utf-8"))
    assert m["app"] == "Ses Defteri" and m["version"] == version.VERSION and m["created"]


# ---------------------------------------------------------------- reading a backup
def test_read_manifest_accepts_ours_and_rejects_foreign_files(tmp_path):
    fill_data()
    ours = tmp_path / "ours.zip"
    backup.create(ours)
    assert backup.read_manifest(ours)["app"] == "Ses Defteri"
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(ValueError):
        backup.read_manifest(plain)  # no manifest
    lying = tmp_path / "lying.zip"
    with zipfile.ZipFile(lying, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "Başka şey"}))
    with pytest.raises(ValueError):
        backup.read_manifest(lying)  # not one of ours
    with pytest.raises(ValueError):
        backup.read_manifest(tmp_path / "yok.zip")  # missing / not a zip


# ---------------------------------------------------------------- restore
def test_restore_roundtrip_and_saves_the_current_data_first(tmp_path):
    root, jid = fill_data()
    bk = tmp_path / "SesDefteri-yedek.zip"
    backup.create(bk)
    # the data folder moves on: the old job's audio is gone, a new job has appeared
    (store.job_path(jid) / "audio.mp3").unlink()
    other = store.create_job("yeni.wav")
    r = backup.restore(bk)
    assert r["restored"] > 0
    assert (store.job_path(jid) / "audio.mp3").read_bytes() == b"mp3"  # back as it was
    assert (store.job_path(other) / "transcript.json").exists()  # extracted over, not wiped
    assert not (root / "manifest.json").exists()  # the manifest is not a data file
    once = list(tmp_path.glob("SesDefteri-onceki-*.zip"))
    assert len(once) == 1  # the previous data was saved first, next to the chosen backup
    assert f"jobs/{other}/transcript.json" in names(once[0])


def test_restore_refuses_paths_escaping_the_folder(tmp_path):
    root, _ = fill_data()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "Ses Defteri", "version": "1.0", "created": "x"}))
        z.writestr("../disari.txt", "evil")
        z.writestr(f"jobs/{store.create_job('a.wav')}/transcript.json", "{}")
    with pytest.raises(ValueError):
        backup.restore(bad)
    assert not (root.parent / "disari.txt").exists()
    assert not (root / "disari.txt").exists()


# ---------------------------------------------------------------- the background thread
def test_run_in_thread_reports_status(tmp_path):
    fill_data()
    out = tmp_path / "th.zip"
    assert backup.status()["busy"] is False
    backup.run_in_thread("backup", lambda: backup.create(out))
    st = wait_done(backup.status)
    assert st["done"] and not st["error"] and st["result"]["path"] == str(out)
    assert out.exists()


def test_run_in_thread_only_one_at_a_time():
    ev = threading.Event()
    backup.run_in_thread("backup", lambda: ev.wait(2) or {"path": "x"})
    assert backup.status()["busy"] is True
    with pytest.raises(ValueError):
        backup.run_in_thread("restore", lambda: None)
    ev.set()
    st = wait_done(backup.status)
    assert st["done"] and not st["error"]


def test_run_in_thread_collects_errors():
    def boom():
        raise RuntimeError("disk full")

    backup.run_in_thread("backup", boom)
    st = wait_done(backup.status)
    assert st["done"] is False and "disk full" in st["error"] and st["result"] is None


# ---------------------------------------------------------------- bridge
class FakeWin:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create_file_dialog(self, kind, **kw):
        self.calls.append(kw)
        return self.answer


def test_bridge_backup_create_then_status(tmp_path):
    fill_data()
    target = tmp_path / "SesDefteri-yedek.zip"
    win = FakeWin(str(target))
    api = bridge.Api(lambda: win)
    r = api.backup_create()
    assert r["started"] is True and win.calls[0]["save_filename"].startswith("SesDefteri-yedek-")
    st = wait_done(api.backup_status)
    assert st["done"] and not st["error"] and target.exists()


def test_bridge_backup_create_cancelled(tmp_path):
    api = bridge.Api(lambda: FakeWin(None))
    assert api.backup_create() == {"cancelled": True}
    assert api.backup_status()["busy"] is False


def test_bridge_restore_pick_checks_the_manifest(tmp_path):
    fill_data()
    bk = tmp_path / "b.zip"
    backup.create(bk)
    api = bridge.Api(lambda: FakeWin(str(bk)))
    r = api.backup_restore_pick()
    assert r["path"] == str(bk) and r["manifest"]["app"] == "Ses Defteri"
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("x", "y")
    api2 = bridge.Api(lambda: FakeWin(str(bad)))
    with pytest.raises(ValueError):
        api2.backup_restore_pick()
    assert api2.backup_status()["busy"] is False  # nothing was started


def test_bridge_restore_runs_in_a_thread(tmp_path):
    fill_data()
    bk = tmp_path / "b.zip"
    backup.create(bk)
    api = bridge.Api(lambda: FakeWin(str(bk)))
    assert api.backup_restore(str(bk)) == {"started": True}
    st = wait_done(api.backup_status)
    assert st["done"] and not st["error"] and st["kind"] == "restore"
    assert list(bk.parent.glob("SesDefteri-onceki-*.zip"))  # the old data was saved first
