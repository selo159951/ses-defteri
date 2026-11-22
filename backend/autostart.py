"""Start with Windows: one value under HKCU\\...\\CurrentVersion\\Run.

Only the installed (frozen) app offers this: from source there is no stable exe path to point at.
`command()` and the registry helpers are kept free of pywebview so they can be tested with a
fake winreg module.
"""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "SesDefteri"


def _load():
    if sys.platform != "win32":
        return None
    try:
        import winreg

        return winreg
    except Exception:
        return None


def supported() -> bool:
    """True only in the installed app on Windows (a fixed exe path exists)."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def command(exe: str | None = None) -> str:
    """The Run value: the exe, quoted, started in the tray."""
    return f'"{exe or sys.executable}" --tray'


def started_in_tray(argv: list[str] | None = None) -> bool:
    """--tray means: start with the window hidden, only the tray icon shows."""
    return "--tray" in (sys.argv if argv is None else argv)


def enabled(reg=None) -> bool:
    reg = reg if reg is not None else _load()
    if reg is None:
        return False
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ)
    except OSError:
        return False
    try:
        return bool(reg.QueryValueEx(key, VALUE)[0])
    except OSError:
        return False
    finally:
        _close(reg, key)


def set_enabled(on: bool, reg=None, exe: str | None = None) -> bool:
    """Write or remove the Run value. Returns whether the registry now matches `on`."""
    reg = reg if reg is not None else _load()
    if reg is None:
        return False
    if on:
        try:
            key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE)
        except OSError:
            return False
        try:
            reg.SetValueEx(key, VALUE, 0, reg.REG_SZ, command(exe))
        except OSError:
            return False
        finally:
            _close(reg, key)
        return True
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE)
    except OSError:
        return True  # nothing there already
    try:
        reg.DeleteValue(key, VALUE)
    except OSError:
        pass  # value was already gone
    finally:
        _close(reg, key)
    return True


def _close(reg, key) -> None:
    try:
        reg.CloseKey(key)
    except Exception:
        pass
