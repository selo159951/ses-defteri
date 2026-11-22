"""System tray icon (pystray). Everything is imported lazily: on an installation without the
optional package, or on a system with no tray, the Settings option is simply hidden.

The icon uses the app icon from assets/. Its menu: open the window, start/stop the meeting
recording, quit. The menu runs in pystray's own thread, so only public Api methods that are
thread-safe (or pywebview's own show/evaluate_js) are called.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

LABELS = {
    "tr": {"open": "Aç", "record": "Toplantıyı kaydet", "stop": "Kaydı durdur", "quit": "Çıkış", "title": "Ses Defteri"},
    "en": {"open": "Open", "record": "Record a meeting", "stop": "Stop recording", "quit": "Quit", "title": "Ses Defteri"},
}


def available() -> bool:
    """pystray and Pillow are installed and this system has a tray."""
    if sys.platform != "win32":
        return False
    try:
        import importlib.util

        return importlib.util.find_spec("pystray") is not None and importlib.util.find_spec("PIL") is not None
    except Exception:
        return False


def icon_path() -> Path | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for name in ("icon-256.png", "icon.ico"):
        p = base / "assets" / name
        if p.exists():
            return p
    return None


def _labels() -> dict:
    try:
        from . import asr

        lang = asr.get_settings().get("ui_lang")
    except Exception:
        lang = None
    return LABELS["en" if lang == "en" else "tr"]


class Tray:
    """One tray icon. `start()` returns False when the optional pieces cannot be loaded."""

    def __init__(self, api, window_getter):
        self._api = api
        self._get_window = window_getter
        self._icon = None

    def start(self) -> bool:
        if self._icon is not None:
            return True
        if not available():
            return False
        try:
            import pystray
            from PIL import Image

            path = icon_path()
            image = Image.open(path) if path else Image.new("RGBA", (64, 64), (30, 30, 30, 255))
            try:
                image.load()
            except Exception:
                pass
            lab = _labels()
            api = self._api

            def recording(_item=None):
                return bool(getattr(api, "_rec", None))

            menu = pystray.Menu(
                pystray.MenuItem(lab["open"], self._show, default=True),
                pystray.MenuItem(lab["record"], self._record, enabled=lambda item: not recording(item)),
                pystray.MenuItem(lab["stop"], self._stop, enabled=lambda item: recording(item)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(lab["quit"], self._quit),
            )
            self._icon = pystray.Icon("SesDefteri", image, lab["title"], menu)
            self._icon.run_detached()
            return True
        except Exception:
            _log.exception("tray icon could not be started")
            self._icon = None
            return False

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    # ---- menu actions ----
    def _show(self, _item=None) -> None:
        try:
            win = self._get_window()
            win.show()
            win.restore()
        except Exception:
            pass

    def _record(self, _item=None) -> None:
        # Start directly (the window may be hidden, so no page dialog can be answered); then let the
        # page show its recording bar. The user clicked "record" in the tray themselves.
        try:
            self._api.start_meeting(None)
        except Exception:
            return
        try:
            self._get_window().evaluate_js("window.onTrayRecord && window.onTrayRecord();")
        except Exception:
            pass

    def _stop(self, _item=None) -> None:
        try:
            self._api.stop_meeting()
        except Exception:
            pass

    def _quit(self, _item=None) -> None:
        try:
            self._api.quit_from_tray()
        except Exception:
            try:
                self._get_window().destroy()
            except Exception:
                pass
