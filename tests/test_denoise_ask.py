"""Noise cleanup question: A/B excerpt popup, timeout fallback, learned threshold, queue not blocked (all synthetic)."""
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import asr, audio, bridge, chunking, denoise, diarize, pipeline, store  # noqa: E402
from backend.merge import Turn, Word  # noqa: E402

SR = 16000
RNG = np.random.default_rng(1)


def _noisy(seconds=30, snr_db=0.0):
    t = np.arange(SR * seconds) / SR
    x = (0.3 * (np.sin(2 * np.pi * 0.7 * t) > 0) * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    n = RNG.standard_normal(len(x)).astype(np.float32)
    return x + np.sqrt(np.mean(x ** 2) / (np.mean(n ** 2) * 10 ** (snr_db / 10))) * n


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SESDEFTERI_SEQUENTIAL", "1")
    pipeline._stop.clear()
    pipeline._order.clear()
    pipeline._answers.clear()
    state = {"audio": _noisy(), "cleaned": 0, "asr_input": []}
    monkeypatch.setattr(audio, "convert", lambda src, dst: (Path(dst).write_bytes(b"x"), (state["audio"], 30.0))[1])
    monkeypatch.setattr(audio, "decode", lambda p: (state["audio"], 30.0))
    monkeypatch.setattr(chunking, "split", lambda s: [(0.0, 30.0)])
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: None)
    monkeypatch.setattr(asr, "status", lambda: {"device_in_use": "cpu"})
    monkeypatch.setattr(asr, "detect_languages", lambda s: [])
    monkeypatch.setattr(denoise, "available", lambda: True)

    def transcribe(samples, duration, progress):
        state["asr_input"].append(samples)
        progress(1.0)
        return [Word(0.0, 0.5, " hi", 1.0)], "en"

    def fake_denoise(samples, progress=None):
        state["cleaned"] += 1
        return np.zeros_like(samples) + 0.001

    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(denoise, "denoise", fake_denoise)
    monkeypatch.setattr(diarize, "diarize", lambda s, p, c=None: (p(1.0), [Turn(0, 30, 0)])[1])
    monkeypatch.setattr(diarize, "refine_by_sentence", lambda s, w, spk, p, m: spk)
    monkeypatch.setattr(diarize, "merge_split_speakers", lambda s, w, spk: spk)
    return state


def _start(tmp_path, name="a.mp3"):
    jid = store.create_job(name)
    pipeline.enqueue(jid)
    th = threading.Thread(target=pipeline.run_job, args=(jid, tmp_path / name), daemon=True)
    th.start()
    return jid, th


# ---------------- the popup event ----------------
def test_noisy_recording_asks_with_excerpt_files_then_user_choice_is_used(fake, tmp_path):
    jid, th = _start(tmp_path)
    assert wait(lambda: store.read_transcript(jid).get("noise_ask"))
    j = store.read_transcript(jid)
    ask = j["noise_ask"]
    assert j["stage"] == "awaiting_choice" and j["status"] == "running"
    assert ask["auto"] is True and ask["snr"] < ask["threshold"]
    jp = store.job_path(jid)
    assert (jp / ask["original"]).exists() and (jp / ask["cleaned"]).exists()  # served by the media host like audio.mp3
    api = bridge.Api(window_getter=lambda: None)
    q = api.get_queue()
    assert q["ask"]["id"] == jid and q["ask"]["original"] == "ab_original.wav"
    assert api.answer_noise(jid, False)["ok"] is True  # the user prefers the original
    th.join(10)
    j = store.read_transcript(jid)
    assert j["status"] == "done" and j["noise"]["cleaned"] is False and j["noise"]["choice"] == "user"
    assert j.get("noise_ask") is None
    assert not (jp / "ab_original.wav").exists() and not (jp / "ab_cleaned.wav").exists()  # removed after the choice
    assert all(np.any(a) for a in fake["asr_input"])  # speech model heard the original
    assert denoise.answers() == [(pytest.approx(j["noise"]["snr"], abs=0.1), False)]


def test_user_choosing_cleaned_cleans_whole_recording(fake, tmp_path):
    jid, th = _start(tmp_path)
    assert wait(lambda: store.read_transcript(jid).get("noise_ask"))
    before = fake["cleaned"]  # the excerpt only
    assert before == 1
    pipeline.answer_noise(jid, True)
    th.join(10)
    j = store.read_transcript(jid)
    assert j["noise"]["cleaned"] is True and fake["cleaned"] == 2


def test_answer_without_question_is_ignored(fake):
    assert pipeline.answer_noise("nope", True) is False


def test_dont_ask_again_switches_to_automatic(fake, tmp_path):
    jid, th = _start(tmp_path)
    assert wait(lambda: store.read_transcript(jid).get("noise_ask"))
    pipeline.answer_noise(jid, True, dont_ask=True)
    th.join(10)
    assert asr.get_settings()["denoise_ask"] is False
    jid2, th2 = _start(tmp_path, "b.mp3")
    th2.join(10)
    j2 = store.read_transcript(jid2)
    assert j2["status"] == "done" and "choice" not in j2["noise"] and j2["noise"]["cleaned"] is True  # automatic, no question


def test_quiet_recording_far_above_threshold_is_not_asked(fake, tmp_path):
    fake["audio"] = _noisy(snr_db=40)
    jid, th = _start(tmp_path)
    th.join(10)
    j = store.read_transcript(jid)
    assert j["status"] == "done" and j["noise"]["cleaned"] is False and fake["cleaned"] == 0


def test_off_and_always_never_ask(fake, tmp_path):
    for mode in ("off", "always"):
        asr.set_setting("denoise", mode)
        jid, th = _start(tmp_path)
        th.join(10)
        assert store.read_transcript(jid)["status"] == "done"


# ---------------- timeout and queue ----------------
def test_timeout_uses_automatic_decision_and_notes_it(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ASK_TIMEOUT", 0.3)
    jid, th = _start(tmp_path)
    th.join(10)
    j = store.read_transcript(jid)
    assert j["status"] == "done" and j["noise"]["choice"] == "timeout" and j["noise"]["cleaned"] is True
    assert denoise.answers() == []  # nothing is learned from a timeout


def test_waiting_job_can_be_paused_and_cancelled(fake, tmp_path):
    jid, th = _start(tmp_path)
    assert wait(lambda: store.read_transcript(jid).get("noise_ask"))
    jp = store.job_path(jid)
    pipeline.request_stop(jid, "pause")
    th.join(10)
    j = store.read_transcript(jid)
    assert j["status"] == "paused" and j.get("noise_ask") is None
    assert not (jp / "ab_original.wav").exists()
    jid2, th2 = _start(tmp_path, "b.mp3")
    assert wait(lambda: store.read_transcript(jid2).get("noise_ask"))
    pipeline.request_stop(jid2, "cancel")
    th2.join(10)
    with pytest.raises(Exception):
        store.read_transcript(jid2)


def test_queue_is_not_blocked_by_unanswered_question(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ASK_TIMEOUT", 0.4)
    j1, t1 = _start(tmp_path, "a.mp3")
    j2, t2 = _start(tmp_path, "b.mp3")
    t1.join(15)
    t2.join(15)
    assert store.read_transcript(j1)["status"] == "done" and store.read_transcript(j2)["status"] == "done"
    assert store.read_transcript(j2)["noise"]["choice"] == "timeout"  # asked per file


def test_each_file_in_the_queue_is_asked(fake, tmp_path):
    j1, t1 = _start(tmp_path, "a.mp3")
    j2, t2 = _start(tmp_path, "b.mp3")
    assert wait(lambda: store.read_transcript(j1).get("noise_ask"))
    assert store.read_transcript(j2)["status"] != "done" and not store.read_transcript(j2).get("noise_ask")
    pipeline.answer_noise(j1, True)
    assert wait(lambda: store.read_transcript(j2).get("noise_ask"))
    pipeline.answer_noise(j2, False)
    t1.join(10)
    t2.join(10)
    assert store.read_transcript(j2)["noise"]["cleaned"] is False


# ---------------- learning ----------------
def test_learning_rule():
    L = denoise.learned_threshold
    assert L([]) == denoise.AUTO_SNR_DB
    # one answer barely moves it
    assert abs(L([(4.0, False)]) - 8) < abs(L([(4.0, False)] * 6) - 8)
    # both sides, full weight: midpoint of highest "cleaned" and lowest "original"
    both = [(5.0, True), (6.0, True), (12.0, False), (14.0, False), (7.0, True), (13.0, False)]
    assert L(both) == pytest.approx((7.0 + 12.0) / 2)
    # only "original" answers: threshold drops below them; only "cleaned": rises above them
    assert L([(6.0, False)] * 6) < 6.0
    assert L([(10.0, True)] * 6) > 10.0
    # always clamped
    assert L([(40.0, True)] * 6) == denoise.THRESH_MAX
    assert L([(-5.0, False)] * 6) == denoise.THRESH_MIN


def test_threshold_follows_recorded_choices_and_resets(fake):
    api = bridge.Api(window_getter=lambda: None)
    assert api.get_settings()["denoise_threshold"] == 8.0
    for s, c in [(5, True), (6, True), (7, True), (12, False), (13, False), (14, False)]:
        denoise.record_choice(s, c)
    st = api.get_settings()
    assert st["denoise_threshold"] == 9.5 and st["denoise_answers"] == 6
    st = api.reset_denoise_threshold()
    assert st["denoise_threshold"] == 8.0 and st["denoise_answers"] == 0
    assert len(([denoise.record_choice(1, True) for _ in range(60)], denoise.answers())[1]) == denoise.KEEP_ANSWERS


def test_ask_rule_band_and_consistent_far_answers():
    thr = 8.0
    assert denoise.should_ask(10.5, [], thr) is True    # just above: asked, to learn both ways
    assert denoise.should_ask(11.5, [], thr) is False   # clearly clean
    assert denoise.should_ask(2.0, [], thr) is True     # noisy, no history
    assert denoise.should_ask(2.0, [(1, True), (2, True), (3, True)], thr) is False  # consistent far-below answers: stop asking
    assert denoise.should_ask(2.0, [(1, True), (2, False), (3, True)], thr) is True
    assert denoise.should_ask(7.0, [(1, True), (2, True), (3, True)], thr) is True   # near threshold: always
    assert denoise.should_ask(2.0, [], thr, enabled=False) is False


def test_pick_excerpt_has_speech_and_is_short():
    x = np.concatenate([_noisy(20, 20), 0.02 * RNG.standard_normal(SR * 30).astype(np.float32), _noisy(20, 3)])
    a, b = denoise.pick_excerpt(x)
    assert b - a == int(denoise.EXCERPT_SECS * SR)
    assert a >= 50 * SR - 1  # the noisiest part that still has speech (the last block), not the silent noise-only middle


def test_next_job_uses_the_learned_threshold(fake, tmp_path):
    asr.set_setting("denoise_ask", False)
    fake["audio"] = _noisy(snr_db=6.0)
    snr = denoise.estimate_snr(fake["audio"])
    for _ in range(6):
        denoise.record_choice(snr + 1.0, False)  # user keeps saying "original" at this level
    assert denoise.current_threshold() < snr
    jid, th = _start(tmp_path)
    th.join(10)
    assert store.read_transcript(jid)["noise"]["cleaned"] is False
