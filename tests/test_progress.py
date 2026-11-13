"""Pause / resume / cancel and the progress fields the step list in the page reads."""
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import store  # noqa: E402
from backend.merge import Turn, Word  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path))
    monkeypatch.setenv("SESDEFTERI_SEQUENTIAL", "1")


class Fakes:
    """Stand-ins for the heavy modules: 3 parts, each reports progress in steps and can wait for a gate."""

    def __init__(self):
        self.gate = threading.Event()      # transcription of the part named in `hold_part` waits for this
        self.hold_part = None
        self.reached = threading.Event()   # set when the held part started
        self.parts_done = []
        self.converted = 0
        self.convert_gate = None


@pytest.fixture
def fakes(monkeypatch):
    from backend import asr, audio, benchmarks, chunking, diarize, pipeline

    f = Fakes()
    samples = np.zeros(16000 * 30, dtype=np.float32)

    def convert(src, mp3, progress=None):
        f.converted += 1
        if progress:
            progress(0.5)
            if f.convert_gate:
                f.reached.set()
                f.convert_gate.wait(5)
                progress(0.9)  # the stop request is noticed here
            progress(1.0)
        Path(mp3).write_bytes(b"mp3")
        return samples, 30.0

    monkeypatch.setattr(audio, "convert", convert)
    monkeypatch.setattr(audio, "decode", lambda p: (samples, 30.0))
    monkeypatch.setattr(chunking, "split", lambda s: [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)])
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: None)
    monkeypatch.setattr(asr, "status", lambda: {"device_in_use": "cpu"})
    monkeypatch.setattr(asr, "detect_languages", lambda s: [("tr", 1.0)])

    def transcribe(chunk, duration, progress):
        n = len(f.parts_done)
        progress(0.5)
        if f.hold_part == n:
            f.reached.set()
            f.gate.wait(5)
            progress(0.9)  # the stop request is noticed here
        progress(1.0)
        f.parts_done.append(n)
        return [Word(0.0, 1.0, " merhaba", 1.0)], "tr"

    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(diarize, "diarize", lambda s, p, c=None: (p(1.0), [Turn(0, 30, 0)])[1])
    monkeypatch.setattr(diarize, "refine_by_sentence", lambda s, w, spk, prog, margins: spk)
    monkeypatch.setattr(diarize, "merge_split_speakers", lambda s, w, spk: spk)
    monkeypatch.setattr(benchmarks, "record", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_parallel_enabled", lambda: False)
    return f


def wait(cond, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def start(tmp_path, name="a.wav"):
    from backend import bridge

    src = tmp_path / name
    src.write_bytes(b"x")
    api = bridge.Api(lambda: None)
    return api, api.start_job(str(src))["id"]


def inactive(job_id):
    from backend import pipeline

    return wait(lambda: not pipeline.is_active(job_id))


def test_full_run_reports_stage_fields(tmp_path, fakes):
    api, jid = start(tmp_path)
    assert inactive(jid)
    j = api.get_job(jid)
    assert j["status"] == "done" and j["progress"] == 1.0 and j["audio_ready"] is True
    assert j["cprogress"] == 1.0 and j["run_started"] and j["heartbeat"] and j["stage_started"]
    assert j["waiting_for"] is None and j["parts"] == [[0.0, 10.0], [10.0, 20.0], [20.0, 30.0]]
    assert j["source_path"].endswith("a.wav")


def test_converting_is_shown_before_slow_imports(tmp_path, fakes, monkeypatch):
    """The cause of the frozen "queued" look: the job stayed queued while the heavy modules were imported."""
    api, jid = start(tmp_path)
    assert inactive(jid)
    # the first thing _run writes is stage "converting"; stage_started is set by enter()
    src = (Path(__file__).resolve().parent.parent / "backend" / "pipeline.py").read_text("utf-8")
    body = src[src.index("def _run("):]
    assert body.index('enter("converting")') < body.index("from . import asr, audio, chunking, diarize")


def test_pause_keeps_parts_and_resume_finishes(tmp_path, fakes):
    from backend import pipeline

    fakes.hold_part = 1
    api, jid = start(tmp_path)
    assert fakes.reached.wait(5)
    api.pause_job(jid)
    fakes.gate.set()
    assert inactive(jid)
    j = api.get_job(jid)
    assert j["status"] == "paused" and j["stage"] == "paused"
    assert (store.job_path(jid) / "parts" / "0.json").exists()
    assert not (store.job_path(jid) / "parts" / "1.json").exists()
    assert fakes.parts_done == [0]
    assert pipeline._stop == {} and not pipeline._queue_lock.locked()
    assert [x["status"] for x in api.list_jobs()] == ["paused"]

    fakes.hold_part = None
    api.resume_job(jid)
    assert inactive(jid)
    j = api.get_job(jid)
    assert j["status"] == "done"
    assert fakes.parts_done == [0, 1, 2]  # part 0 was not transcribed again
    assert fakes.converted == 1           # the saved mp3 was reused


def test_cancel_removes_job_without_error(tmp_path, fakes):
    from backend import pipeline

    fakes.hold_part = 0
    api, jid = start(tmp_path)
    assert fakes.reached.wait(5)
    assert api.cancel_job(jid)["ok"]
    fakes.gate.set()
    assert inactive(jid)
    assert api.list_jobs() == []
    assert not store.job_path(jid).exists()
    assert pipeline._stop == {} and not pipeline._queue_lock.locked()
    with pytest.raises(ValueError):
        api.get_job(jid)


def test_pause_while_converting_resumes_from_original_file(tmp_path, fakes):
    fakes.convert_gate = threading.Event()
    api, jid = start(tmp_path)
    assert fakes.reached.wait(5)
    api.pause_job(jid)
    fakes.convert_gate.set()
    assert inactive(jid)
    j = api.get_job(jid)
    assert j["status"] == "paused" and not j["audio_ready"]
    assert not (store.job_path(jid) / "audio.mp3").exists()  # the half written file is removed
    fakes.convert_gate = None
    api.resume_job(jid)
    assert inactive(jid)
    assert api.get_job(jid)["status"] == "done" and fakes.converted == 2


def test_queued_job_names_the_one_in_front_and_can_be_stopped(tmp_path, fakes):
    from backend import pipeline

    fakes.hold_part = 0
    api, first = start(tmp_path, "first.wav")
    assert fakes.reached.wait(5)
    api2, second = start(tmp_path, "second.wav")
    assert wait(lambda: api.get_job(second).get("waiting_for") == "first.wav")
    j = api.get_job(second)
    assert j["status"] == "queued" and j["stage"] == "queued"
    # a queued job can be paused at once, without waiting for the first one
    api.pause_job(second)
    assert inactive(second)
    assert api.get_job(second)["status"] == "paused" and api.get_job(second)["waiting_for"] is None
    # ... and cancelled while it is paused (nothing is running for it)
    assert api.cancel_job(second)["ok"] and not store.job_path(second).exists()
    # a third one cancelled while queued
    api3, third = start(tmp_path, "third.wav")
    assert wait(lambda: api.get_job(third).get("waiting_for") == "first.wav")
    api.cancel_job(third)
    assert inactive(third) and not store.job_path(third).exists()
    fakes.gate.set()
    assert inactive(first)
    assert api.get_job(first)["status"] == "done"
    assert not pipeline._queue_lock.locked()


def test_pause_and_resume_validation(tmp_path, fakes):
    api, jid = start(tmp_path)
    assert inactive(jid)
    with pytest.raises(ValueError):
        api.pause_job(jid)      # finished: nothing to pause
    with pytest.raises(ValueError):
        api.resume_job(jid)     # finished: nothing to resume
    with pytest.raises(ValueError):
        api.cancel_job(jid)     # finished: delete instead


def test_cancel_during_speaker_separation_sets_event(tmp_path, fakes, monkeypatch):
    from backend import diarize, pipeline

    seen = threading.Event()

    def diar(samples, progress, cancel=None):
        seen.set()
        for i in range(200):
            progress(i / 200)  # raises JobStopped once the stop is requested
            time.sleep(0.01)
        return [Turn(0, 30, 0)]

    monkeypatch.setattr(diarize, "diarize", diar)
    api, jid = start(tmp_path)
    assert seen.wait(5)
    api.pause_job(jid)
    assert inactive(jid)
    assert api.get_job(jid)["status"] == "paused"
    assert pipeline._cancel_events == {}


def test_request_stop_ignores_unknown_job_and_bad_mode():
    from backend import pipeline

    assert pipeline.request_stop("nope", "pause") is False
    with pytest.raises(ValueError):
        pipeline.request_stop("nope", "explode")


def test_audio_convert_reports_progress(tmp_path):
    import wave

    from backend import audio

    p = tmp_path / "t.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.zeros(16000 * 5, dtype=np.int16).tobytes())
    seen = []
    samples, dur = audio.convert(p, tmp_path / "o.mp3", seen.append)
    assert abs(dur - 5.0) < 0.1 and seen and all(0 <= x <= 1 for x in seen)


def test_settings_keep_tour_flags(tmp_path):
    from backend import bridge

    api = bridge.Api(lambda: None)
    assert api.get_settings()["tour_home_done"] is False
    api.set_settings({"tour_home_done": True, "tour_job_done": True})
    s = api.get_settings()
    assert s["tour_home_done"] is True and s["tour_job_done"] is True


def test_progress_ui_wiring():
    root = Path(__file__).resolve().parent.parent / "frontend"
    html = (root / "index.html").read_text("utf-8")
    for needle in ("simple-progress.js", "simple-tour.js", 'id="psteps"', 'id="tourBtn"', "Nasıl kullanılır?"):
        assert needle in html
    assert "tour.js\"" not in html.replace("simple-tour.js", "")
    js = (root / "simple-progress.js").read_text("utf-8")
    for needle in ("Duraklat", "İptal", "Devam et", "Bu işlem iptal edilsin mi? Yapılan kısım silinir.",
                   "Sırada bekliyor: önce şu kayıt bitecek", "Çalışıyor, bilgisayarı kapatmayın",
                   "Dosya hazırlanıyor", "Ses tanıma modeli yükleniyor", "Konuşmalar yazıya dökülüyor",
                   "Konuşmacılar ayrılıyor", "Bitti", "İlk seferde 1-2 dakika sürebilir", "bölüm"):
        assert needle in js


# ---------------- several files at once ----------------
@pytest.fixture
def recorder(fakes, monkeypatch):
    """Fake engine that records the order of the jobs and how many run at the same time."""
    from backend import audio

    class R:
        order, live, peak = [], 0, 0
        lock = threading.Lock()
        fail = set()
        slow = 0.05

    r = R()
    r.order, r.lock, r.fail = [], threading.Lock(), set()
    real = audio.convert

    def convert(src, mp3, progress=None):
        with r.lock:
            r.live += 1
            r.peak = max(r.peak, r.live)
            r.order.append(Path(src).name)
        try:
            time.sleep(r.slow)
            if Path(src).name in r.fail:
                raise ValueError("bozuk dosya")
            return real(src, mp3, progress)
        finally:
            with r.lock:
                r.live -= 1

    monkeypatch.setattr(audio, "convert", convert)
    monkeypatch.setattr(audio, "decode", lambda p: (np.zeros(16000 * 30, dtype=np.float32), 30.0))
    return r


def start_many(tmp_path, names):
    from backend import bridge

    api = bridge.Api(lambda: None)
    paths = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x")
        paths.append(str(p))
    return api, api.start_jobs(paths)


def all_idle(ids):
    from backend import pipeline

    return wait(lambda: not any(pipeline.is_active(i) for i in ids), 20)


def test_many_jobs_run_in_submission_order_one_at_a_time(tmp_path, recorder):
    names = [f"f{i}.wav" for i in range(6)]
    api, res = start_many(tmp_path, names)
    ids = [r["id"] for r in res]
    assert all_idle(ids)
    assert recorder.order == names and recorder.peak == 1
    assert all(api.get_job(i)["status"] == "done" for i in ids)


def test_queue_listing_and_cancel_of_a_queued_middle_job(tmp_path, recorder):
    recorder.slow = 0.4
    api, res = start_many(tmp_path, ["a.wav", "b.wav", "c.wav"])
    a, b, c = (r["id"] for r in res)
    assert wait(lambda: api.get_queue()["running"] and api.get_queue()["running"]["id"] == a)
    assert [x["id"] for x in api.get_queue()["queued"]] == [b, c]
    assert api.cancel_job(b)["ok"]
    assert all_idle([a, b, c])
    assert recorder.order == ["a.wav", "c.wav"]
    assert not store.job_path(b).exists() and api.get_job(c)["status"] == "done"


def test_pause_running_lets_next_start_and_resume_goes_to_the_end(tmp_path, recorder, fakes):
    fakes.hold_part = 0
    api, res = start_many(tmp_path, ["a.wav", "b.wav", "c.wav"])
    a, b, c = (r["id"] for r in res)
    assert fakes.reached.wait(5)
    api.pause_job(a)
    fakes.gate.set()
    fakes.hold_part = None
    assert wait(lambda: api.get_job(a)["status"] == "paused")
    api.resume_job(a)  # b and c are still ahead of it
    assert all_idle([a, b, c])
    assert recorder.order == ["a.wav", "b.wav", "c.wav"]
    assert [api.get_job(i)["status"] for i in (a, b, c)] == ["done"] * 3
    # the resumed a started its second run after c's run began: it went to the end of the line
    assert api.get_job(a)["run_started"] > api.get_job(c)["run_started"] and recorder.peak == 1


def test_failing_job_does_not_stop_the_queue(tmp_path, recorder):
    recorder.fail = {"bad.wav"}
    api, res = start_many(tmp_path, ["a.wav", "bad.wav", "c.wav"])
    ids = [r["id"] for r in res]
    assert all_idle(ids)
    st = [api.get_job(i) for i in ids]
    assert [j["status"] for j in st] == ["done", "error", "done"]
    assert "bozuk" in st[1]["error"]


def test_same_file_twice_and_same_name_get_separate_jobs(tmp_path, recorder):
    d2 = tmp_path / "other"
    d2.mkdir()
    (tmp_path / "x.wav").write_bytes(b"x")
    (d2 / "x.wav").write_bytes(b"y")
    from backend import bridge

    api = bridge.Api(lambda: None)
    res = api.start_jobs([str(tmp_path / "x.wav"), str(tmp_path / "x.wav"), str(d2 / "x.wav")])
    ids = [r["id"] for r in res]
    assert len(set(ids)) == 3 and all_idle(ids)
    assert len({store.job_path(i) for i in ids}) == 3
    assert all((store.job_path(i) / "audio.mp3").exists() and api.get_job(i)["status"] == "done" for i in ids)


def test_folder_and_non_media_are_skipped_with_a_message(tmp_path, recorder):
    from backend import bridge

    (tmp_path / "klasor").mkdir()
    (tmp_path / "not.txt").write_text("x")
    (tmp_path / "ok.wav").write_bytes(b"x")
    api = bridge.Api(lambda: None)
    res = api.start_jobs([str(tmp_path / "klasor"), str(tmp_path / "not.txt"), str(tmp_path / "yok.wav"), str(tmp_path / "ok.wav")])
    assert [bool(r.get("skipped")) for r in res] == [True, True, True, False]
    assert "klasör" in res[0]["error"] and "ses ya da video" in res[1]["error"]
    assert all_idle([res[3]["id"]]) and len(api.list_jobs()) == 1


def test_concurrent_update_job_keeps_every_field_and_valid_file(tmp_path):
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
