import sys
import threading
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import asr, audio, bridge, chunking, diarize, pipeline, store  # noqa: E402
from backend.merge import Turn, Word  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))
    monkeypatch.setenv("SESDEFTERI_SEQUENTIAL", "1")
    pipeline._stop.clear()


@pytest.fixture
def fake(monkeypatch):
    """Three parts; the hook runs when a part is transcribed (lets a test stop the job mid-way)."""
    state = {"calls": [], "hook": None}

    def convert(src, dst):
        Path(dst).write_bytes(b"x")
        return np.zeros(16000 * 30, dtype=np.float32), 30.0

    def transcribe(samples, duration, progress):
        state["calls"].append(duration)
        if state["hook"]:
            state["hook"](len(state["calls"]))
        progress(0.5)
        progress(1.0)
        return [Word(0.0, 0.5, " hi", 1.0)], "en"

    monkeypatch.setattr(audio, "convert", convert)
    monkeypatch.setattr(audio, "decode", lambda p: (np.zeros(16000 * 30, dtype=np.float32), 30.0))
    monkeypatch.setattr(chunking, "split", lambda s: [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)])
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: None)
    monkeypatch.setattr(asr, "status", lambda: {"device_in_use": "cpu"})
    monkeypatch.setattr(asr, "detect_languages", lambda s: [])
    monkeypatch.setattr(asr, "transcribe", transcribe)

    def fake_diarize(s, p, c=None):
        p(1.0)
        return [Turn(0, 30, 0)]

    monkeypatch.setattr(diarize, "diarize", fake_diarize)
    monkeypatch.setattr(diarize, "refine_by_sentence", lambda s, w, spk, p, m: spk)
    monkeypatch.setattr(diarize, "merge_split_speakers", lambda s, w, spk: spk)
    return state


def _job(name="a.mp3"):
    return store.create_job(name)


def test_pause_keeps_parts_and_resume_finishes(fake, tmp_path, monkeypatch):
    jid = _job()
    fake["hook"] = lambda n: pipeline.request_stop(jid, "pause") if n == 2 else None
    pipeline.run_job(jid, tmp_path / "a.mp3")
    j = store.read_transcript(jid)
    assert j["status"] == "paused"
    parts = store.job_path(jid) / "parts"
    assert (parts / "0.json").exists() and not (parts / "1.json").exists()  # stopped inside part 2
    assert jid not in pipeline._stop

    fake["hook"] = None
    fake["calls"].clear()
    done = threading.Event()
    real = pipeline.run_job
    monkeypatch.setattr(bridge, "run_job", lambda *a, **kw: (real(*a, **kw), done.set()))
    bridge.Api(window_getter=lambda: None).resume_job(jid)
    assert done.wait(10)
    assert store.read_transcript(jid)["status"] == "done"
    assert len(fake["calls"]) == 2  # part 1 was not transcribed again


def test_cancel_removes_the_job(fake, tmp_path):
    jid = _job()
    fake["hook"] = lambda n: pipeline.request_stop(jid, "cancel")
    pipeline.run_job(jid, tmp_path / "a.mp3")
    assert not store.job_path(jid).exists()
    assert store.list_jobs() == [] and jid not in pipeline._stop


def test_stop_before_start_and_lock_released(fake, tmp_path):
    jid, other = _job("a.mp3"), _job("b.mp3")
    pipeline.request_stop(jid, "pause")
    pipeline.run_job(jid, tmp_path / "a.mp3")
    assert store.read_transcript(jid)["status"] == "paused" and fake["calls"] == []
    assert pipeline._queue_lock.acquire(blocking=False)  # released
    pipeline._queue_lock.release()
    pipeline.run_job(other, tmp_path / "b.mp3")
    assert store.read_transcript(other)["status"] == "done"


def test_cancel_queued_job_while_another_runs(fake, tmp_path):
    first, queued = _job("a.mp3"), _job("b.mp3")
    api = bridge.Api(window_getter=lambda: None)
    entered, release = threading.Event(), threading.Event()

    def hook(n):
        if n == 1:
            entered.set()
            assert release.wait(10)

    fake["hook"] = hook
    t1 = threading.Thread(target=pipeline.run_job, args=(first, tmp_path / "a.mp3"))
    t1.start()
    assert entered.wait(10)
    store.update_job(queued, status="queued", stage="queued")
    t2 = threading.Thread(target=pipeline.run_job, args=(queued, tmp_path / "b.mp3"))
    t2.start()
    api.cancel_job(queued)
    assert not store.job_path(queued).exists()
    release.set()
    t1.join(10)
    t2.join(10)
    assert store.read_transcript(first)["status"] == "done"
    assert not store.job_path(queued).exists() and pipeline._stop == {}


def test_bridge_pause_cancel_rules():
    api = bridge.Api(window_getter=lambda: None)
    jid = _job()
    store.update_job(jid, status="paused", stage="transcribing")
    with pytest.raises(ValueError):
        api.pause_job(jid)
    assert api.cancel_job(jid) == {"ok": True}
    assert store.list_jobs() == []
