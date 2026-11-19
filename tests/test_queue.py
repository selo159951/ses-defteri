"""Several files at once: first-in-first-out line, one heavy job at a time, bad files skipped."""
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import analysis, asr, audio, bridge, chunking, diarize, pipeline, store  # noqa: E402
from backend.merge import Turn, Word  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SESDEFTERI_SEQUENTIAL", "1")
    pipeline._stop.clear()
    pipeline._order.clear()


def wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def rec(monkeypatch):
    """Fake engine that records the order of the jobs and how many run at the same time."""
    class R:
        order, live, peak = [], 0, 0
        lock = threading.Lock()
        fail = set()
        slow = 0.05
        hook = None

    r = R()
    r.order, r.lock, r.fail = [], threading.Lock(), set()

    def convert(src, dst):
        with r.lock:
            r.live += 1
            r.peak = max(r.peak, r.live)
            r.order.append(Path(src).name)
        try:
            time.sleep(r.slow)
            if Path(src).name in r.fail:
                raise ValueError("broken file")
            Path(dst).write_bytes(b"x")
            return np.zeros(16000 * 30, dtype=np.float32), 30.0
        finally:
            with r.lock:
                r.live -= 1

    def transcribe(samples, duration, progress):
        if r.hook:
            r.hook()
        progress(1.0)
        return [Word(0.0, 0.5, " hi", 1.0)], "en"

    monkeypatch.setattr(audio, "convert", convert)
    monkeypatch.setattr(audio, "decode", lambda p: (np.zeros(16000 * 30, dtype=np.float32), 30.0))
    monkeypatch.setattr(chunking, "split", lambda s: [(0.0, 30.0)])
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: None)
    monkeypatch.setattr(asr, "status", lambda: {"device_in_use": "cpu"})
    monkeypatch.setattr(asr, "detect_languages", lambda s: [])
    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(diarize, "diarize", lambda s, p, c=None: (p(1.0), [Turn(0, 30, 0)])[1])
    monkeypatch.setattr(diarize, "refine_by_sentence", lambda s, w, spk, p, m: spk)
    monkeypatch.setattr(diarize, "merge_split_speakers", lambda s, w, spk: spk)
    return r


def start_many(tmp_path, names):
    api = bridge.Api(lambda: None)
    paths = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x")
        paths.append(str(p))
    return api, api.start_jobs(paths)


def all_idle(ids):
    def idle():
        return pipeline._current["id"] is None and not pipeline.queue_ids() and all(
            store.read_transcript(i)["status"] in ("done", "error", "paused") for i in ids if store.job_path(i).exists())
    return wait(idle, 30)


def test_many_jobs_run_in_submission_order_one_at_a_time(tmp_path, rec):
    names = [f"f{i}.wav" for i in range(6)]
    api, res = start_many(tmp_path, names)
    ids = [r["id"] for r in res]
    assert all_idle(ids)
    assert rec.order == names and rec.peak == 1
    assert all(api.get_job(i)["status"] == "done" for i in ids)


def test_queue_listing_and_cancel_of_a_queued_middle_job(tmp_path, rec):
    rec.slow = 0.5
    api, res = start_many(tmp_path, ["a.wav", "b.wav", "c.wav"])
    a, b, c = (r["id"] for r in res)
    assert wait(lambda: api.get_queue()["running"] and api.get_queue()["running"]["id"] == a)
    assert [x["id"] for x in api.get_queue()["queued"]] == [b, c]
    assert api.get_queue()["queued"][0]["filename"] == "b.wav"
    assert api.cancel_job(b)["ok"]
    assert all_idle([a, c])
    assert rec.order == ["a.wav", "c.wav"]
    assert not store.job_path(b).exists() and api.get_job(c)["status"] == "done"
    assert api.get_queue() == {"running": None, "ask": None, "queued": []}


def test_pause_running_lets_next_start_and_resume_goes_to_the_end(tmp_path, rec):
    entered, release = threading.Event(), threading.Event()

    def hook():
        if not entered.is_set():  # only the first transcription (a.wav) is held
            entered.set()
            assert release.wait(10)
    rec.hook = hook
    api, res = start_many(tmp_path, ["a.wav", "b.wav", "c.wav"])
    a, b, c = (r["id"] for r in res)
    assert entered.wait(10)
    api.pause_job(a)
    release.set()
    assert wait(lambda: api.get_job(a)["status"] == "paused")
    api.resume_job(a)  # b and c are still ahead of it
    assert pipeline.queue_ids()[-1] == a
    assert all_idle([a, b, c])
    assert [api.get_job(i)["status"] for i in (a, b, c)] == ["done"] * 3
    assert rec.order == ["a.wav", "b.wav", "c.wav"] and rec.peak == 1  # the resumed a had its audio already, no new convert


def test_pause_a_queued_job_only_leaves_the_line(tmp_path, rec):
    rec.slow = 0.4
    api, res = start_many(tmp_path, ["a.wav", "b.wav", "c.wav"])
    a, b, c = (r["id"] for r in res)
    assert wait(lambda: api.get_queue()["running"])
    api.pause_job(b)
    assert all_idle([a, b, c])
    assert [api.get_job(i)["status"] for i in (a, b, c)] == ["done", "paused", "done"]
    assert rec.order == ["a.wav", "c.wav"] and pipeline.queue_ids() == []


def test_failing_job_does_not_stop_the_queue(tmp_path, rec):
    rec.fail = {"bad.wav"}
    api, res = start_many(tmp_path, ["a.wav", "bad.wav", "c.wav"])
    ids = [r["id"] for r in res]
    assert all_idle(ids)
    st = [api.get_job(i) for i in ids]
    assert [j["status"] for j in st] == ["done", "error", "done"]
    assert "broken" in st[1]["error"]


def test_same_file_twice_and_same_name_get_separate_jobs(tmp_path, rec):
    d2 = tmp_path / "other"
    d2.mkdir()
    (tmp_path / "x.wav").write_bytes(b"x")
    (d2 / "x.wav").write_bytes(b"y")
    api = bridge.Api(lambda: None)
    res = api.start_jobs([str(tmp_path / "x.wav"), str(tmp_path / "x.wav"), str(d2 / "x.wav")])
    ids = [r["id"] for r in res]
    assert len(set(ids)) == 3 and all_idle(ids)
    assert len({store.job_path(i) for i in ids}) == 3
    assert all((store.job_path(i) / "audio.mp3").exists() and api.get_job(i)["status"] == "done" for i in ids)


def test_folder_and_non_media_are_skipped_with_a_code(tmp_path, rec):
    (tmp_path / "dir").mkdir()
    (tmp_path / "not.txt").write_text("x")
    (tmp_path / "ok.wav").write_bytes(b"x")
    api = bridge.Api(lambda: None)
    res = api.start_jobs([str(tmp_path / "dir"), str(tmp_path / "not.txt"), str(tmp_path / "gone.wav"), str(tmp_path / "ok.wav")])
    assert [bool(r.get("skipped")) for r in res] == [True, True, True, False]
    assert [r["code"] for r in res[:3]] == ["folder", "not_media", "missing"]
    assert "folder" in res[0]["error"] and "not an audio or video" in res[1]["error"]
    assert res[0]["filename"] == "dir"
    assert all_idle([res[3]["id"]]) and len(api.list_jobs()) == 1
    with pytest.raises(ValueError):
        api.start_job(str(tmp_path / "dir"))


def test_pick_and_start_accepts_several_files_and_cancel(tmp_path, rec):
    for n in ("p1.wav", "p2.wav"):
        (tmp_path / n).write_bytes(b"x")

    class Win:
        result = None

        def create_file_dialog(self, *a, **kw):
            assert kw.get("allow_multiple") is True
            return self.result

    win = Win()
    api = bridge.Api(lambda: win)
    win.result = None
    assert api.pick_and_start() == []
    win.result = (str(tmp_path / "p1.wav"), str(tmp_path / "p2.wav"))
    res = api.pick_and_start()
    assert [r["filename"] for r in res] == ["p1.wav", "p2.wav"]
    assert all_idle([r["id"] for r in res]) and rec.order == ["p1.wav", "p2.wav"]


def test_meeting_analysis_waits_for_the_queue_lock(tmp_path, monkeypatch):
    """The analysis model must never run while a transcription is in progress."""
    jid = store.create_job("m.wav")
    store.update_job(jid, segments=[{"id": 0, "start": 0, "end": 1, "speaker": 0, "text_original": "a", "text_edited": "a", "words": []}],
                     speakers={"0": "Speaker 1"})
    ran = threading.Event()
    monkeypatch.setattr(analysis, "run", lambda j, ev=None, **k: ran.set())
    monkeypatch.setattr(analysis, "llm_ready", lambda: True)
    with pipeline._queue_lock:  # a transcription holds the lock
        analysis.start(jid)
        assert not ran.wait(0.8)
    assert ran.wait(5)
    assert wait(lambda: jid not in analysis._events)


def test_cancelling_an_analysis_that_is_waiting_for_the_lock(tmp_path, monkeypatch):
    jid = store.create_job("m.wav")
    store.update_job(jid, segments=[{"id": 0, "start": 0, "end": 1, "speaker": 0, "text_original": "a", "text_edited": "a", "words": []}],
                     speakers={"0": "Speaker 1"})
    calls = []
    monkeypatch.setattr(analysis, "run", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(analysis, "llm_ready", lambda: True)
    with pipeline._queue_lock:
        analysis.start(jid)
        analysis.cancel(jid)
        assert wait(lambda: store.read_transcript(jid)["analysis"]["state"] == "cancelled")
    assert calls == []


def test_concurrent_update_job_keeps_every_field_and_valid_file():
    jid = store.create_job("c.wav")
    N, T = 40, 8

    def work(t):
        for i in range(N):
            store.update_job(jid, **{f"f_{t}_{i}": i})
            if i % 10 == 0:
                store.list_jobs()
                store.rename_job(jid, f"name{t}")

    ths = [threading.Thread(target=work, args=(t,)) for t in range(T)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    d = store.read_transcript(jid)
    assert sum(1 for k in d if k.startswith("f_")) == N * T
    assert d["id"] == jid and d["segments"] == []
    assert [p.name for p in store.job_path(jid).iterdir()] == ["transcript.json"]  # no temp files left


def test_the_tests_use_a_temp_home(tmp_path):
    assert str(store.data_dir()).startswith(str(tmp_path))
