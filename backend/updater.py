"""Update check: the app's only network call besides model downloads the user starts.

At start (a few seconds after the window opens) the app reads a small version file from the author's site. When a newer
version exists it shows a banner. On "Update" it downloads the setup of its own edition (standard / NVIDIA / simple) from
GitHub, checks size, SHA-256 and the "Selim Oğuz" signature, and runs it silently after the app has closed. The setup only
writes the program folder; recordings, people, settings and models in %APPDATA% are never touched.

Turn it off with the setting "update_check" (Settings page). No data is sent: a plain GET with the version in User-Agent.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import asr
from .version import SIGNER_THUMBPRINT, VERSION, edition, is_newer, parse

UPDATE_URL = "https://selimoguz.com.tr/ses-defteri/surum.json"
DOWNLOAD_PREFIX = "https://github.com/selo159951/ses-defteri/releases/download/"
CHECK_TIMEOUT = 5
SNOOZE_SECS = 24 * 3600
MAX_MANIFEST = 64 * 1024
# Status of a self-signed signature: the hash is intact, Windows just does not know the root ("UnknownError"/"NotTrusted").
GOOD_STATUS = {"Valid", "UnknownError", "NotTrusted"}

_lock = threading.Lock()
_state: dict = {"state": "idle"}
_manifest: dict | None = None


def manifest_url() -> str:
    return os.environ.get("SESDEFTERI_UPDATE_URL") or UPDATE_URL


def _test_mode() -> bool:
    """A test server set through SESDEFTERI_UPDATE_URL may serve the setups itself (http://127.0.0.1/...)."""
    return bool(os.environ.get("SESDEFTERI_UPDATE_URL"))


def update_dir() -> Path:
    return Path(tempfile.gettempdir()) / "SesDefteri-update"


def _ua() -> str:
    return f"SesDefteri/{VERSION} ({edition()})"


def _set(**kw) -> dict:
    with _lock:
        _state.clear()
        _state.update(kw)
        return dict(_state)


def status(lang: str = "tr") -> dict:
    """What the banner and the Settings page show."""
    with _lock:
        s = dict(_state)
    m = _manifest or {}
    s.update(current=VERSION, edition=edition(), enabled=enabled(),
             can_install=edition() != "dev" and os.name == "nt")
    if m:
        s.update(latest=m.get("version"), date=m.get("date", ""),
                 notes=m.get(f"notes_{lang}") or m.get("notes_tr") or m.get("notes_en") or "")
    return s


def enabled() -> bool:
    return asr.get_settings().get("update_check", True) is not False


# ---------------------------------------------------------------- manifest
def validate(m) -> dict:
    """The parts of surum.json the app relies on; raises ValueError on anything else."""
    if not isinstance(m, dict) or not isinstance(m.get("version"), str) or parse(m["version"]) == (0,):
        raise ValueError("no version")
    files = m.get("files")
    if not isinstance(files, dict):
        raise ValueError("no files")
    for ed, f in files.items():
        if not isinstance(f, dict) or not isinstance(f.get("url"), str):
            raise ValueError(f"bad entry {ed}")
        sha = str(f.get("sha256", "")).lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError(f"bad sha256 {ed}")
        if not isinstance(f.get("size"), int) or f["size"] <= 0:
            raise ValueError(f"bad size {ed}")
        if not (f["url"].startswith(DOWNLOAD_PREFIX) or _test_mode()):
            raise ValueError(f"download not from the GitHub release: {ed}")
    return m


def fetch_manifest(url: str | None = None, opener=urllib.request.urlopen) -> dict:
    req = urllib.request.Request(url or manifest_url(), headers={"User-Agent": _ua(), "Cache-Control": "no-cache"})
    with opener(req, timeout=CHECK_TIMEOUT) as r:
        raw = r.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise ValueError("version file too large")
    return validate(json.loads(raw.decode("utf-8-sig")))


def _snoozed(version: str) -> bool:
    s = asr.get_settings().get("update_snooze") or {}
    return isinstance(s, dict) and s.get("version") == version and time.time() < float(s.get("until", 0))


def snooze() -> dict:
    """"Later": this version is not offered again for a day."""
    if _manifest:
        asr.set_setting("update_snooze", {"version": _manifest["version"], "until": time.time() + SNOOZE_SECS})
    return _set(state="snoozed")


def check(force: bool = False, opener=urllib.request.urlopen) -> dict:
    """force: the "Check now" button (also works when automatic checks are off, and ignores "Later")."""
    global _manifest
    with _lock:
        busy = _state.get("state") in ("checking", "downloading", "ready")
    if busy:
        return status()
    if not force and not enabled():
        return _set(state="off")
    _set(state="checking")
    _cleanup()
    try:
        m = fetch_manifest(opener=opener)
    except Exception as e:  # offline, site down, broken file: stay quiet unless asked
        _manifest = None
        return _set(state="error" if force else "idle", error=str(e)[:200])
    _manifest = m
    if not is_newer(m["version"]):
        return _set(state="none")
    if edition() not in m["files"] and edition() != "dev":
        return _set(state="none", error="no file for this edition")
    if not force and _snoozed(m["version"]):
        return _set(state="snoozed")
    return _set(state="available")


# ---------------------------------------------------------------- download
def _cleanup() -> None:
    """Setups from earlier runs are not needed any more."""
    shutil.rmtree(update_dir(), ignore_errors=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def signature(path: Path) -> tuple[str, str]:
    """(status, signer thumbprint) from Windows (Get-AuthenticodeSignature)."""
    if os.name != "nt":
        return "NotSupported", ""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:SD_UPDATE_FILE; "
              "Write-Output ([string]$s.Status + '|' + [string]$s.SignerCertificate.Thumbprint)")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60, env={**os.environ, "SD_UPDATE_FILE": str(path)},
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    st, _, tp = out.stdout.strip().rpartition("\n")[-1].partition("|")
    return st.strip(), tp.strip().upper()


def verify(path: Path, entry: dict, sig=signature) -> str | None:
    """None when the file is the one the version file describes and signed by us; otherwise the reason."""
    if path.stat().st_size != entry["size"]:
        return "size"
    if _sha256(path) != entry["sha256"].lower():
        return "sha256"
    if not SIGNER_THUMBPRINT:
        return "no signer configured"
    st, tp = sig(path)
    if st not in GOOD_STATUS or tp != SIGNER_THUMBPRINT.upper():
        return f"signature {st or '-'}"
    return None


def download(opener=urllib.request.urlopen, sig=signature, background: bool = True) -> dict:
    with _lock:
        if _state.get("state") not in ("available", "error", "snoozed") or not _manifest:
            return dict(_state)
    entry = _manifest["files"].get(edition())
    if not entry:
        return _set(state="error", error="no file for this edition")
    _set(state="downloading", progress=0)
    t = threading.Thread(target=_download, args=(entry, opener, sig), daemon=True)
    t.start()
    if not background:
        t.join()
    return status()


def _download(entry: dict, opener, sig) -> None:
    d = update_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = entry["url"].rsplit("/", 1)[-1].split("?")[0] or "SesDefteri-Setup.exe"
    final, part = d / name, d / (name + ".part")
    try:
        for attempt in range(4):  # the connection to GitHub sometimes drops: continue where it stopped
            have = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": _ua()}
            if have:
                headers["Range"] = f"bytes={have}-"
            try:
                with opener(urllib.request.Request(entry["url"], headers=headers), timeout=60) as r:
                    if have and getattr(r, "status", 200) != 206:
                        have = 0  # server ignored the range: start over
                    with open(part, "ab" if have else "wb") as f:
                        while chunk := r.read(1 << 20):
                            f.write(chunk)
                            have += len(chunk)
                            with _lock:
                                _state["progress"] = min(99, int(have * 100 / entry["size"]))
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        os.replace(part, final)
        why = verify(final, entry, sig)
        if why:
            final.unlink(missing_ok=True)
            _set(state="error", error=f"check failed: {why}")
            return
        _set(state="ready", progress=100, path=str(final))
    except Exception as e:
        _set(state="error", error=str(e)[:200])


# ---------------------------------------------------------------- install
def install_command(setup: str, pid: int) -> tuple[list[str], dict]:
    """Waits for this app to close, then runs the setup silently; the setup starts the app again when done."""
    log = str(Path(setup).with_suffix(".log"))
    script = ("Wait-Process -Id $env:SD_PID -Timeout 120 -ErrorAction SilentlyContinue; "
              "Start-Process -FilePath $env:SD_SETUP -ArgumentList "
              "'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CLOSEAPPLICATIONS',('/LOG=\"' + $env:SD_LOG + '\"')")
    return ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script], {
        "SD_PID": str(pid), "SD_SETUP": setup, "SD_LOG": log}


def install(quit_app, pid: int | None = None, popen=subprocess.Popen) -> dict:
    with _lock:
        ready = _state.get("state") == "ready" and _state.get("path")
        setup = _state.get("path")
    if not ready:
        return status()
    if edition() == "dev" or os.name != "nt":
        return _set(**{**_state, "error": "not an installed app"})
    cmd, env = install_command(setup, pid or os.getpid())
    # no DETACHED_PROCESS: PowerShell started without a console exits at once and never runs the setup
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    popen(cmd, env={**os.environ, **env}, creationflags=flags, close_fds=True)
    _set(state="installing")
    quit_app()
    return status()


def reset() -> None:
    """Tests."""
    global _manifest
    _manifest = None
    _set(state="idle")
