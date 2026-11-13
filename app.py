"""Ses Defteri - desktop app (no web server, no open ports).

Whatever goes wrong while starting ends in a Turkish message box and a log file in
%APPDATA%\\SesDefteriBasit\\logs - never in a window that just closes."""
import sys
import traceback


def _fatal(msg: str) -> None:
    try:
        print(msg, file=sys.stderr or sys.__stderr__)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, msg, "Ses Defteri", 0x10 | 0x10000)
        except Exception:
            pass


def _start_failed(e: BaseException, log) -> None:
    text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    try:
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(text)
    except Exception:
        pass
    try:
        from backend import compat

        _fatal(compat.MSG_GENERIC_START.format(err=f"{type(e).__name__}: {e}"[:600], log=log or "-"))
    except Exception:
        _fatal(f"Ses Defteri açılamadı: {type(e).__name__}: {e}")


def main():
    log = None
    try:
        from backend import compat, store

        store.migrate_old_data()
        log = compat.install_crash_logging()  # also gives a windowed exe a stdout and stderr

        problem = compat.startup_problem()
        if problem:  # old Windows, zip not extracted, WebView2 missing, ...
            compat.message_box(problem, 0x10)
            return
        compat.startup_warnings()

        import webview

        from backend.bridge import Api
        from backend.window import START_URL, attach_file_drop, install_virtual_hosts

        store.mark_interrupted()  # jobs cut off by closing the app can be resumed
        if sys.platform == "win32":
            install_virtual_hosts()
        api = Api()
        # starts maximized; the size below is what "restore down" gives
        window = webview.create_window("Ses Defteri", START_URL, width=1180, height=820,
                                       min_size=(720, 560), maximized=True, js_api=api)
        api._get_window = lambda: window
        attached = []

        def on_loaded():
            if not attached:  # the page is loaded once; register the drop handler once
                attach_file_drop(window, api)
                attached.append(True)

        window.events.loaded += on_loaded
        webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(store.data_dir() / "webview"))
    except SystemExit:
        raise
    except BaseException as e:
        _start_failed(e, log)


if __name__ == "__main__":
    main()
