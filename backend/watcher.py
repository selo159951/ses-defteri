"""Folder watch (off by default): new audio / video files that appear in one chosen folder are queued by themselves.

Plain polling every few seconds, no extra dependency and no network. A file is taken only when
  - it has a known media extension (no .part / .tmp / "~$..." / hidden files),
  - it is new: made after the watch was switched on (or its folder was chosen),
  - it is complete: size and modification time stayed the same for STABLE_SECS and it can be opened,
  - it was not processed before: path + size + modification time are remembered in data_dir/watch_seen.json.
A folder that is missing (USB stick, network drive) only pauses the watch; it resumes when the folder is back.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import asr, store

POLL_SECS = 3.0
STABLE_SECS = 5.0
MEDIA_SUFFIXES = {".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".opus", ".flac", ".aac", ".webm", ".mkv", ".mov",
                  ".wma", ".amr", ".3gp"}
_SEEN_MAX = 2000


def is_candidate(name: str) -> bool:
    """A file name worth looking at: known media extension, not a temp / partial / hidden file."""
    n = name.lower()
    if n.startswith(("~$", ".", "~")) or n.endswith(("~", ".part", ".tmp", ".crdownload", ".partial", ".temp")):
        return False
    return Path(n).suffix in MEDIA_SUFFIXES


def _seen_file() -> Path:
    return store.data_dir() / "watch_seen.json"


def _key(path: Path, size: int, mtime: float) -> str:
    return f"{os.path.normcase(str(path))}|{size}|{int(mtime * 1000)}"


def _can_open(path: Path) -> bool:
    """False while another program still holds the file for writing (Windows refuses a read-write open then)."""
    try:
        with open(path, "r+b"):
            return True
    except PermissionError:
        return False
    except OSError:
        try:  # read-only file: reading is enough
            with open(path, "rb"):
                return True
        except OSError:
            return False


class Watcher:
    def __init__(self, start_jobs, stable_secs: float = STABLE_SECS, poll_secs: float = POLL_SECS):
        self._start_jobs = start_jobs  # callable(list[str]) -> list
        self.stable_secs = stable_secs
        self.poll_secs = poll_secs
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[int, float, float]] = {}  # path -> (size, mtime, since when unchanged)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.queued = 0
        self.last_file = ""
        self.note = ""  # "", "missing", "no_folder"

    # ---- settings
    @staticmethod
    def config() -> dict:
        s = asr.get_settings()
        return {"enabled": bool(s.get("watch_enabled", False)), "dir": s.get("watch_dir") or "",
                "since": float(s.get("watch_since") or 0)}

    def status(self) -> dict:
        c = self.config()
        note = self.note
        if c["enabled"] and c["dir"] and not os.path.isdir(c["dir"]):
            note = "missing"
        return {"enabled": c["enabled"], "dir": c["dir"], "note": note if c["enabled"] else "",
                "queued": self.queued, "last_file": self.last_file,
                "waiting": len(self._pending)}

    def set_dir(self, d: str) -> None:
        asr.set_setting("watch_dir", d)
        asr.set_setting("watch_since", time.time())  # only files made from now on
        with self._lock:
            self._pending.clear()

    def set_enabled(self, on: bool) -> None:
        if on and not self.config()["dir"]:
            raise ValueError("choose a folder first")
        if on:
            asr.set_setting("watch_since", time.time())
        asr.set_setting("watch_enabled", bool(on))
        with self._lock:
            self._pending.clear()
        self.note = ""
        if on:
            self.start()
        else:
            self.stop()

    # ---- seen list
    @staticmethod
    def _load_seen() -> dict:
        try:
            return json.loads(_seen_file().read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save_seen(seen: dict) -> None:
        if len(seen) > _SEEN_MAX:
            for k in sorted(seen, key=seen.get)[: len(seen) - _SEEN_MAX]:
                del seen[k]
        f = _seen_file()
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen), "utf-8")
        tmp.replace(f)

    # ---- one look at the folder
    def scan(self, now: float | None = None) -> list[str]:
        """Look once; return the files that are ready (complete and new) and remember them as seen."""
        now = time.time() if now is None else now
        c = self.config()
        if not c["enabled"] or not c["dir"]:
            self.note = "no_folder" if c["enabled"] else ""
            return []
        folder = Path(c["dir"])
        try:
            # close the directory handle at once: otherwise Windows keeps the folder busy
            with os.scandir(folder) as it:
                entries = [e for e in it if e.is_file() and is_candidate(e.name)]
        except OSError:
            self.note = "missing"
            self._pending.clear()
            return []
        self.note = ""
        seen = self._load_seen()
        ready: list[str] = []
        present = set()
        for e in sorted(entries, key=lambda e: e.name.lower()):
            try:
                st = os.stat(e.path)  # not e.stat(): on Windows that size is stale while a writer keeps the file open
            except OSError:
                continue
            p = Path(e.path)
            sp = str(p)
            present.add(sp)
            if max(st.st_mtime, st.st_ctime) < c["since"] - 1 or st.st_size == 0:
                continue  # was there before the watch started / nothing written yet
            if _key(p, st.st_size, st.st_mtime) in seen:
                continue
            prev = self._pending.get(sp)
            if not prev or prev[0] != st.st_size or prev[1] != st.st_mtime:
                self._pending[sp] = (st.st_size, st.st_mtime, now)  # still changing: start counting again
                continue
            if now - prev[2] >= self.stable_secs and _can_open(p):
                ready.append(sp)
                seen[_key(p, st.st_size, st.st_mtime)] = now
        for sp in list(self._pending):
            if sp not in present or sp in ready:
                self._pending.pop(sp, None)
        if ready:
            self._save_seen(seen)
        return ready

    def tick(self, now: float | None = None) -> list:
        ready = self.scan(now)
        if ready:
            res = self._start_jobs(ready)
            self.queued += sum(1 for r in res if not r.get("skipped"))
            self.last_file = Path(ready[-1]).name
            return res
        return []

    # ---- thread
    def _run(self, stop: threading.Event) -> None:
        while not stop.wait(self.poll_secs):
            try:
                self.tick()
            except Exception:
                pass  # never let the watch thread die on one odd file

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._thread = None
