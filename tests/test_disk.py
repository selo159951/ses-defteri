"""Disk space limits and deleting the audio of old recordings (transcripts stay)."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import disk, store  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


def test_classify_limits():
    assert disk.classify(10 * 1024 ** 3) == "ok"
    assert disk.classify(disk.LOW_FREE) == "ok"
    assert disk.classify(disk.LOW_FREE - 1) == "low"
    assert disk.classify(disk.MIN_FREE) == "low"
    assert disk.classify(disk.MIN_FREE - 1) == "full"


def test_check_reports_bytes_and_state(monkeypatch):
    class Usage:
        free = 1024 ** 3  # 1 GB

    monkeypatch.setattr(disk, "_free", lambda _p: Usage())
    assert disk.check() == {"state": "low", "free": 1024 ** 3}


def test_free_bytes_does_not_block_when_measurement_fails(monkeypatch):
    def boom(_p):
        raise OSError("no such drive")

    monkeypatch.setattr(disk, "_free", boom)
    assert disk.free_bytes() == disk.MIN_FREE


def _done_job(name, created):
    job_id = store.create_job(name)
    store.update_job(job_id, status="done", created=created)
    audio = store.job_path(job_id) / "audio.mp3"
    audio.write_bytes(b"fake mp3")
    return job_id, audio


def test_purge_deletes_only_old_done_audio():
    now = time.time()
    old_id, old_audio = _done_job("old.mp3", now - 40 * 86400)
    new_id, new_audio = _done_job("new.mp3", now - 2 * 86400)
    run_id, run_audio = _done_job("running.mp3", now - 100 * 86400)
    store.update_job(run_id, status="running")

    assert disk.purge_old_audio(30, now=now) == 1
    assert not old_audio.exists()
    assert store.read_transcript(old_id)["audio_deleted"] is True
    assert new_audio.exists()
    assert run_audio.exists()  # a job that is still running is never touched


def test_purge_never_when_days_is_off():
    now = time.time()
    _, audio = _done_job("old.mp3", now - 400 * 86400)
    assert disk.purge_old_audio(0, now=now) == 0
    assert audio.exists()


def test_purge_keeps_transcript_text():
    now = time.time()
    job_id, audio = _done_job("old.mp3", now - 40 * 86400)
    store.update_job(job_id, segments=[{"id": 0, "start": 0, "end": 1, "speaker": 0,
                                        "text_edited": "merhaba", "text_original": "merhaba", "words": []}])
    disk.purge_old_audio(30, now=now)
    data = store.read_transcript(job_id)
    assert data["segments"][0]["text_edited"] == "merhaba"
    assert not audio.exists()


def test_start_meeting_refused_when_disk_is_full(monkeypatch):
    from backend.bridge import Api

    monkeypatch.setattr(disk, "check", lambda *a, **k: {"state": "full", "free": 100 * 1024 ** 2})
    api = Api(window_getter=lambda: None)
    out = api.start_meeting(None)
    assert out["error"] == "disk_full" and out["active"] is False


def test_start_job_refused_when_disk_is_full(tmp_path, monkeypatch):
    from backend.bridge import Api, SkipFile

    monkeypatch.setattr(disk, "check", lambda *a, **k: {"state": "full", "free": 100 * 1024 ** 2})
    src = tmp_path / "meeting.mp3"
    src.write_bytes(b"x")
    api = Api(window_getter=lambda: None)
    with pytest.raises(SkipFile) as err:
        api.start_job(str(src))
    assert err.value.code == "disk_full"


def test_low_disk_still_starts_and_returns_a_warning(tmp_path, monkeypatch):
    from backend.bridge import Api
    from backend import pipeline

    monkeypatch.setattr(disk, "check", lambda *a, **k: {"state": "low", "free": 1024 ** 3})
    started = []
    monkeypatch.setattr(pipeline, "enqueue", lambda job_id: started.append(job_id))
    monkeypatch.setattr("backend.bridge.run_job", lambda *a, **k: None)
    src = tmp_path / "meeting.mp3"
    src.write_bytes(b"x")
    api = Api(window_getter=lambda: None)
    out = api.start_job(str(src))
    assert out["warning"] == {"code": "disk_low", "free": 1024 ** 3}
    assert started and store.read_transcript(out["id"])["filename"] == "meeting.mp3"
