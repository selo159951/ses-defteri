"""The desktop window: WebView2 serves the UI and audio straight from disk.

No port is opened. pywebview would normally start a local HTTP server for local
files; instead we map two virtual host names to folders inside WebView2
(SetVirtualHostNameToFolderMapping), which only this window can resolve:

  https://app.sesdefteri/    -> frontend/      (the UI)
  https://media.sesdefteri/  -> data/jobs/     (each recording's audio.mp3)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import store

APP_HOST = "app.sesdefteri"
MEDIA_HOST = "media.sesdefteri"
START_URL = f"https://{APP_HOST}/index.html"


def frontend_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "frontend"


def install_virtual_hosts() -> None:
    """Patch pywebview's WebView2 start-up so the folders are mapped before the first load."""
    from webview.platforms import edgechromium
    from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind

    original = edgechromium.EdgeChrome.on_webview_ready
    if getattr(original, "_meet_patched", False):
        return

    def on_webview_ready(self, sender, args):
        if args.IsSuccess:
            core = sender.CoreWebView2
            allow = CoreWebView2HostResourceAccessKind.Allow
            core.SetVirtualHostNameToFolderMapping(APP_HOST, str(frontend_dir()), allow)
            core.SetVirtualHostNameToFolderMapping(MEDIA_HOST, str(store.jobs_dir()), allow)
        return original(self, sender, args)

    on_webview_ready._meet_patched = True
    edgechromium.EdgeChrome.on_webview_ready = on_webview_ready


def attach_file_drop(window, api) -> None:
    """Dropped files arrive with their full path (pywebview DOM events); start a job for each."""
    from webview.dom import DOMEventHandler

    def on_drop(event):
        paths = [f.get("pywebviewFullPath") for f in (event.get("dataTransfer") or {}).get("files", [])]
        paths = [p for p in paths if p]
        if not paths:
            res = [{"skipped": True, "filename": "", "error": "Bu bir dosya değil. Ses ya da video dosyasını sürükle."}]
            window.evaluate_js(f"window.onJobsStarted && window.onJobsStarted({json.dumps(res)})")
            return
        try:
            res = api.start_jobs(paths)  # in dropped order; a bad file is reported, the rest go on
            window.evaluate_js(f"window.onJobsStarted && window.onJobsStarted({json.dumps(res)})")
        except Exception as e:  # shown to the user
            res = [{"skipped": True, "filename": "", "error": str(e)}]
            window.evaluate_js(f"window.onJobsStarted && window.onJobsStarted({json.dumps(res)})")

    window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=True)
