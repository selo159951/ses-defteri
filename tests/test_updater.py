"""Update check: version compare, version-file checks, download with resume, size/SHA-256/signature checks, silent install."""
import hashlib
import io
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import asr, updater, version  # noqa: E402

SETUP = b"MZ" + b"setup-bytes " * 5000
URL = updater.DOWNLOAD_PREFIX + "v9.9.0/SesDefteri-Setup.exe"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SESDEFTERI_EDITION", "standart")
    monkeypatch.delenv("SESDEFTERI_UPDATE_URL", raising=False)
    monkeypatch.setattr(updater, "update_dir", lambda: tmp_path / "upd")
    updater.reset()
    yield
    updater.reset()


def manifest(ver="9.9.0", data=SETUP, **over):
    entry = {"url": URL, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    m = {"version": ver, "date": "2026-12-01", "notes_tr": "Yeni", "notes_en": "New",
         "files": {"standart": dict(entry), "nvidia": dict(entry), "basit": dict(entry)}}
    m.update(over)
    return m


class Resp(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(m, setup=SETUP, fail_after=None, ignore_range=False):
    calls = []

    def op(req, timeout=None):
        calls.append(req)
        if req.full_url.endswith(".json"):
            return Resp(json.dumps(m).encode())
        rng = req.headers.get("Range")
        if rng and not ignore_range:
            start = int(rng.split("=")[1].rstrip("-"))
            return Resp(setup[start:], 206)
        if fail_after is not None and len(calls) <= 2:  # first download attempt breaks halfway
            class Broken(Resp):
                def read(self, n=-1):
                    if self.tell() >= fail_after:
                        raise ConnectionResetError("dropped")
                    return super().read(min(n, fail_after - self.tell()))
            return Broken(setup)
        return Resp(setup)
    op.calls = calls
    return op


def good_sig(path):
    return "UnknownError", version.SIGNER_THUMBPRINT


# ---------------------------------------------------------------- versions
@pytest.mark.parametrize("a,b,newer", [
    ("1.3.0", "1.2.0", True), ("1.10.0", "1.9.0", True), ("1.3", "1.3.0", False), ("v1.3.1", "1.3.0", True),
    ("1.3.0", "1.3.0", False), ("1.2.9", "1.3.0", False), ("2.0.0-beta", "1.9.9", True), ("junk", "1.0.0", False),
])
def test_is_newer(a, b, newer):
    assert version.is_newer(a, b) is newer


def test_edition_dev_and_override(monkeypatch):
    monkeypatch.delenv("SESDEFTERI_EDITION")
    assert version.edition() == "dev"
    monkeypatch.setenv("SESDEFTERI_EDITION", "nvidia")
    assert version.edition() == "nvidia"


# ---------------------------------------------------------------- version file
@pytest.mark.parametrize("bad", [
    {}, {"version": "1.4.0"}, {"version": "x", "files": {}},
    manifest(files={"standart": {"url": URL, "size": 5, "sha256": "abc"}}),
    manifest(files={"standart": {"url": URL, "size": 0, "sha256": "a" * 64}}),
    manifest(files={"standart": {"url": "https://evil.example/s.exe", "size": 5, "sha256": "a" * 64}}),
])
def test_validate_rejects(bad):
    with pytest.raises(ValueError):
        updater.validate(bad)


def test_check_finds_newer_version():
    s = updater.check(opener=opener_for(manifest()))
    assert s["state"] == "available"
    st = updater.status("en")
    assert st["latest"] == "9.9.0" and st["notes"] == "New" and st["current"] == version.VERSION


def test_check_same_version_says_none():
    assert updater.check(opener=opener_for(manifest(ver=version.VERSION)))["state"] == "none"


def test_offline_is_quiet_unless_asked():
    def down(req, timeout=None):
        raise OSError("no network")
    assert updater.check(opener=down)["state"] == "idle"
    assert updater.check(force=True, opener=down)["state"] == "error"


def test_turned_off_does_not_touch_network():
    asr.set_setting("update_check", False)
    op = opener_for(manifest())
    assert updater.check(opener=op)["state"] == "off"
    assert op.calls == []
    assert updater.check(force=True, opener=op)["state"] == "available"  # "Check now" still works


def test_later_hides_this_version_for_a_day():
    op = opener_for(manifest())
    updater.check(opener=op)
    updater.snooze()
    updater.reset()
    assert updater.check(opener=op)["state"] == "snoozed"
    assert updater.check(force=True, opener=op)["state"] == "available"
    asr.set_setting("update_snooze", {"version": "9.9.0", "until": time.time() - 1})
    updater.reset()
    assert updater.check(opener=op)["state"] == "available"
    updater.reset()
    assert updater.check(opener=opener_for(manifest(ver="9.9.1")))["state"] == "available"  # a newer one shows again


def test_edition_without_file_is_not_offered(monkeypatch):
    monkeypatch.setenv("SESDEFTERI_EDITION", "basit")
    m = manifest()
    del m["files"]["basit"]
    assert updater.check(opener=opener_for(m))["state"] == "none"


# ---------------------------------------------------------------- download
def test_download_verifies_and_is_ready():
    op = opener_for(manifest())
    updater.check(opener=op)
    updater.download(opener=op, sig=good_sig, background=False)
    s = updater.status()
    assert s["state"] == "ready" and s["progress"] == 100
    assert Path(s["path"]).read_bytes() == SETUP


def test_download_resumes_after_dropped_connection(monkeypatch):
    monkeypatch.setattr(updater.time, "sleep", lambda s: None)
    op = opener_for(manifest(), fail_after=20000)
    updater.check(opener=op)
    updater.download(opener=op, sig=good_sig, background=False)
    assert updater.status()["state"] == "ready"
    assert any(r.headers.get("Range") == "bytes=20000-" for r in op.calls)


@pytest.mark.parametrize("what,why", [("sha", "sha256"), ("size", "size"), ("sig", "signature"), ("signer", "signature")])
def test_bad_file_is_never_installed(what, why):
    data = SETUP
    m = manifest()
    if what == "sha":
        m["files"]["standart"]["sha256"] = "0" * 64
    if what == "size":
        m["files"]["standart"]["size"] = len(data) + 1
    sig = {"sig": lambda p: ("HashMismatch", version.SIGNER_THUMBPRINT),
           "signer": lambda p: ("UnknownError", "ABCDEF")}.get(what, good_sig)
    op = opener_for(m, data)
    updater.check(opener=op)
    updater.download(opener=op, sig=sig, background=False)
    s = updater.status()
    assert s["state"] == "error" and why in s["error"]
    assert not list((updater.update_dir()).glob("*.exe"))


# ---------------------------------------------------------------- install
def test_install_waits_for_app_then_runs_silent_setup(monkeypatch):
    monkeypatch.setattr(updater.os, "name", "nt")
    op = opener_for(manifest())
    updater.check(opener=op)
    updater.download(opener=op, sig=good_sig, background=False)
    ran, quit_called = [], []
    updater.install(lambda: quit_called.append(1), pid=4242, popen=lambda cmd, **kw: ran.append((cmd, kw)))
    assert quit_called and updater.status()["state"] == "installing"
    cmd, kw = ran[0]
    script = cmd[-1]
    assert "Wait-Process" in script and "/VERYSILENT" in script and "/SUPPRESSMSGBOXES" in script
    assert kw["env"]["SD_PID"] == "4242" and kw["env"]["SD_SETUP"].endswith("SesDefteri-Setup.exe")


def test_install_refused_from_source(monkeypatch):
    monkeypatch.setenv("SESDEFTERI_EDITION", "dev")
    op = opener_for(manifest())
    updater.check(opener=op)
    updater._set(state="ready", path="x.exe")
    ran = []
    updater.install(lambda: ran.append("quit"), popen=lambda *a, **k: ran.append("run"))
    assert ran == []
