"""Is a meeting app using the microphone right now?

Windows records microphone use of every app under
  HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone
An entry whose LastUsedTimeStop is 0 is *using the microphone now* (it is set to a timestamp when
the app lets go). Packaged apps keep their values on the app's own key; classic programs live
under the NonPackaged subkey, their `#`-separated path used as the key name.

The parsing is a pure function over {name: LastUsedTimeStop} so it can be tested with fake data.
A background thread refreshes the answer every few seconds; the page polls `meeting_detect_status`.
"""
from __future__ import annotations

import logging
import os
import sys
import threading

_log = logging.getLogger(__name__)

MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

# Registry name fragment -> the name shown in the banner. Browsers mean a meeting in the browser
# (Google Meet, Teams web, …); the banner simply says "Meet".
APPS = (
    ("teams", "Teams"),
    ("zoom", "Zoom"),
    ("webex", "Webex"),
    ("slack", "Slack"),
    ("discord", "Discord"),
)
BROWSERS = ("chrome", "msedge", "firefox", "brave", "opera")


def default_ignore() -> tuple[str, ...]:
    """Our own process must never trigger the suggestion (we would be using the mic while recording)."""
    out = {"sesdefteri"}
    try:
        out.add(os.path.basename(sys.executable).lower())
    except Exception:
        pass
    return tuple(sorted(x for x in out if x))


def label_for(name: str, ignore: tuple[str, ...] | list[str] = ()) -> str | None:
    """Friendly app name for a registry entry, or None when it is not a meeting app / is ours."""
    low = (name or "").lower().replace("#", "\\")
    if any(x and x in low for x in ignore):
        return None
    for fragment, label in APPS:
        if fragment in low:
            return label
    if any(browser in low for browser in BROWSERS):
        return "Meet"
    return None


def detect(usage: dict, ignore: tuple[str, ...] | list[str] = ()) -> dict | None:
    """First meeting app that is using the microphone now, as {"app", "name"}; else None.

    `usage` maps a registry entry name to its LastUsedTimeStop value (0 = still using the mic).
    """
    for name in sorted(usage or {}):
        try:
            stop = int(usage[name])
        except (TypeError, ValueError):
            continue
        if stop != 0:
            continue
        label = label_for(name, ignore)
        if label:
            return {"app": label, "name": name}
    return None


def _value(reg, key, name: str):
    try:
        return int(reg.QueryValueEx(key, name)[0])
    except (OSError, TypeError, ValueError):
        return None


def _walk(reg, key, prefix: str, out: dict) -> None:
    i = 0
    while True:
        try:
            sub_name = reg.EnumKey(key, i)
        except OSError:
            return
        i += 1
        try:
            sub = reg.OpenKey(key, sub_name)
        except OSError:
            continue
        try:
            full = f"{prefix}\\{sub_name}" if prefix else sub_name
            stop = _value(reg, sub, "LastUsedTimeStop")
            if stop is not None:
                out[full.replace("#", "\\")] = stop
            _walk(reg, sub, full, out)
        finally:
            try:
                reg.CloseKey(sub)
            except Exception:
                pass


def read_usage(reg=None) -> dict:
    """{entry name: LastUsedTimeStop} from the microphone consent store. {} when unavailable."""
    if reg is None:
        if sys.platform != "win32":
            return {}
        try:
            import winreg

            reg = winreg
        except Exception:
            return {}
    try:
        root = reg.OpenKey(reg.HKEY_CURRENT_USER, MIC_KEY)
    except OSError:
        return {}
    out: dict = {}
    try:
        _walk(reg, root, "", out)
    except Exception:
        _log.exception("could not read the microphone consent store")
    finally:
        try:
            reg.CloseKey(root)
        except Exception:
            pass
    return out


def _exe_name(pid: int) -> str:
    """Executable file name of a process (no extra dependency: Windows API through ctypes)."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def read_capture() -> dict:
    """{program path: 0 (recording from a microphone now) / 1 (session open but idle)} from the Windows audio
    sessions of every active microphone. Newer Windows builds no longer keep LastUsedTimeStop in the consent
    store, so this is the main source; it needs comtypes/pycaw and answers {} without them."""
    if sys.platform != "win32":
        return {}
    try:
        import comtypes
        from comtypes import CLSCTX_ALL
        from pycaw.constants import CLSID_MMDeviceEnumerator
        from pycaw.pycaw import DEVICE_STATE, EDataFlow, IAudioSessionControl2, IAudioSessionManager2, IMMDeviceEnumerator
    except Exception:
        return {}
    out: dict = {}
    try:
        comtypes.CoInitialize()
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        devices = enum.EnumAudioEndpoints(EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value)
        for i in range(devices.GetCount()):
            mgr = devices.Item(i).Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
            sessions = mgr.GetSessionEnumerator()
            for j in range(sessions.GetCount()):
                c = sessions.GetSession(j).QueryInterface(IAudioSessionControl2)
                pid = c.GetProcessId()
                name = _exe_name(pid) if pid else ""
                if name:
                    active = c.GetState() == 1  # AudioSessionStateActive
                    out[name] = 0 if active or out.get(name) == 0 else 1
    except Exception:
        _log.exception("could not read the audio sessions")
    return out


def read_all() -> dict:
    """Both sources: the audio sessions (now) and the consent store (older Windows)."""
    return {**read_usage(), **read_capture()}


class Detector:
    """Reads the consent store in the background; `snapshot()` is cheap and lock-protected."""

    def __init__(self, interval: float = 5.0, reader=None, ignore=None):
        self.interval = max(1.0, float(interval))
        self._reader = reader or read_all
        self._ignore = tuple(ignore if ignore is not None else default_ignore())
        self._state = {"active": False, "app": None, "name": None}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="meeting-detect", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll(self) -> dict:
        try:
            hit = detect(self._reader(), self._ignore)
        except Exception:
            _log.exception("meeting detection failed")
            hit = None
        state = {"active": bool(hit), "app": (hit or {}).get("app"), "name": (hit or {}).get("name")}
        with self._lock:
            self._state = state
        return dict(state)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(self.interval)
