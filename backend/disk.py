"""Disk space checks and deleting the audio of old recordings.

The data folder lives on one drive: a recording, its temporary parts and the model output all
need room there. Two limits are used:

  under 2 GB free -> recording still starts, but the user is warned ("a long meeting may not fit")
  under 300 MB    -> recording is refused

`purge_old_audio` deletes only the audio.mp3 of *finished* jobs older than the chosen number of
days. The transcript, speakers and analysis stay; the recording page then has no player.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import store

LOW_FREE = 2 * 1024 ** 3      # 2 GB
MIN_FREE = 300 * 1024 ** 2    # 300 MB
PURGE_DAYS = (0, 30, 90, 180)  # 0 = never

_free = shutil.disk_usage  # replaced in tests


def free_bytes(path: Path | str | None = None) -> int:
    """Free space on the drive that holds `path` (the data folder by default)."""
    target = Path(path) if path else store.data_dir()
    try:
        return int(_free(str(target)).free)
    except OSError:
        return MIN_FREE  # unknown drive: do not block work over a failed measurement


def classify(free: int) -> str:
    """ok | low | full. Pure, so the two limits can be tested without touching a disk."""
    if free < MIN_FREE:
        return "full"
    if free < LOW_FREE:
        return "low"
    return "ok"


def check(path: Path | str | None = None) -> dict:
    """{"state": ok|low|full, "free": bytes} for the data folder's drive."""
    free = free_bytes(path)
    return {"state": classify(free), "free": free}


def purge_old_audio(days: int | None = None, now: float | None = None) -> int:
    """Delete audio.mp3 of finished jobs older than `days` and mark the job.

    The transcript is kept: the page shows "the audio file was deleted". Returns how many files
    were removed. `days` 0 (or anything not offered in Settings) does nothing.
    """
    if days is None:
        from .asr import get_settings

        try:
            days = int(get_settings().get("purge_audio_days", 0) or 0)
        except (TypeError, ValueError):
            days = 0
    if days not in PURGE_DAYS[1:]:
        return 0
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    removed = 0
    for item in store.list_jobs():
        if item.get("status") != "done":
            continue
        created = item.get("created") or 0
        if created > cutoff:
            continue
        audio = store.job_path(item["id"]) / "audio.mp3"
        if not audio.is_file():
            continue
        try:
            audio.unlink()
        except OSError:
            continue  # in use or already gone: try again at the next start
        removed += 1
        try:
            store.update_job(item["id"], audio_deleted=True)
        except (OSError, ValueError):
            pass
    return removed
