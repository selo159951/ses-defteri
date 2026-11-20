import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import asr, audio, bridge, chunking, denoise, diarize, pipeline, store  # noqa: E402
from backend.merge import Turn, Word  # noqa: E402

SR = 16000
RNG = np.random.default_rng(0)


@pytest.fixture(autouse=True)
def _temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))


def _speechlike(seconds=20):
    """Bursts of a 300 Hz tone shaped like words, with silent gaps."""
    t = np.arange(SR * seconds) / SR
    env = (np.sin(2 * np.pi * 0.7 * t) > 0).astype(np.float32)
    return (0.3 * env * np.sin(2 * np.pi * 300 * t)).astype(np.float32)


def _with_noise(x, snr_db):
    noise = RNG.standard_normal(len(x)).astype(np.float32)
    g = np.sqrt(np.mean(x ** 2) / (np.mean(noise ** 2) * 10 ** (snr_db / 10)))
    return x + g * noise


def test_snr_estimate_orders_recordings():
    x = _speechlike()
    clean = denoise.estimate_snr(x + 1e-4 * RNG.standard_normal(len(x)).astype(np.float32))
    mid = denoise.estimate_snr(_with_noise(x, 10))
    bad = denoise.estimate_snr(_with_noise(x, 0))
    assert clean > mid > bad
    assert clean > denoise.AUTO_SNR_DB > bad


def test_snr_estimate_edge_cases():
    assert denoise.estimate_snr(np.zeros(SR * 10, dtype=np.float32)) == 99.0  # silence
    assert denoise.estimate_snr(np.zeros(100, dtype=np.float32)) == 99.0  # too short


def test_policy_modes():
    quiet = _speechlike() + 1e-4 * RNG.standard_normal(SR * 20).astype(np.float32)
    noisy = _with_noise(_speechlike(), 0)
    assert denoise.should_denoise("off", noisy)[0] is False
    assert denoise.should_denoise("always", quiet)[0] is True
    assert denoise.should_denoise("auto", quiet)[0] is False
    assert denoise.should_denoise("auto", noisy)[0] is True
    assert denoise.should_denoise("nonsense", noisy)[0] is True  # unknown value = default (auto): noisy -> clean
    assert denoise.should_denoise("nonsense", quiet)[0] is False
    assert denoise.normalize_mode(None) == denoise.DEFAULT_MODE


def test_denoise_keeps_length_across_blocks(monkeypatch):
    """Overlapping blocks are cross-faded back to exactly the input length (identity model = same signal)."""
    class Res:
        def __init__(self, s): self.samples = s

    class Fake:
        def run(self, x, sr): return Res(np.array(x))

    monkeypatch.setattr(denoise, "_load", lambda: Fake())
    monkeypatch.setattr(denoise, "BLOCK", SR * 5)
    monkeypatch.setattr(denoise, "FADE", SR // 2)
    x = RNG.standard_normal(SR * 17 + 123).astype(np.float32)
    seen = []
    y = denoise.denoise(x, seen.append)
    assert len(y) == len(x)
    assert np.allclose(x, y, atol=1e-4)
    assert seen[-1] == 1.0


# ---------------- the pipeline calls the cleaner only when expected ----------------
@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path))
    monkeypatch.setenv("SESDEFTERI_SEQUENTIAL", "1")
    pipeline._stop.clear()
    asr.set_setting("denoise_ask", False)  # these tests are about the automatic decision; the popup has its own tests
    state = {"audio": _speechlike(30), "cleaned": 0, "asr_input": [], "diar_input": []}

    monkeypatch.setattr(audio, "convert", lambda src, dst, progress=None: (Path(dst).write_bytes(b"x"), (state["audio"], 30.0))[1])
    monkeypatch.setattr(audio, "decode", lambda p: (state["audio"], 30.0))
    monkeypatch.setattr(chunking, "split", lambda s: [(0.0, 15.0), (15.0, 30.0)])
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
        if progress:
            progress(1.0)
        return np.zeros_like(samples)  # recognisable: all zero

    def fake_diarize(s, p, c=None):
        state["diar_input"].append(s)
        p(1.0)
        return [Turn(0, 30, 0)]

    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(denoise, "denoise", fake_denoise)
    monkeypatch.setattr(diarize, "diarize", fake_diarize)
    monkeypatch.setattr(diarize, "refine_by_sentence", lambda s, w, spk, p, m: spk)
    monkeypatch.setattr(diarize, "merge_split_speakers", lambda s, w, spk: spk)
    return state


def _run(tmp_path, mode=None):
    if mode:
        asr.set_setting("denoise", mode)
    (tmp_path / "a.mp3").write_bytes(b"x")
    jid = store.create_job("a.mp3")
    pipeline.run_job(jid, tmp_path / "a.mp3")
    j = store.read_transcript(jid)
    return jid, j


def test_default_is_auto(fake, tmp_path):
    fake["audio"] = _with_noise(_speechlike(30), 0)
    jid, j = _run(tmp_path)
    assert fake["cleaned"] == 1 and j["noise"]["mode"] == "auto"


def test_off_never_cleans(fake, tmp_path):
    fake["audio"] = _with_noise(_speechlike(30), 0)
    jid, j = _run(tmp_path, "off")
    assert j["status"] == "done" and fake["cleaned"] == 0
    assert j["noise"]["cleaned"] is False
    assert all(np.any(a) for a in fake["asr_input"])


def test_auto_skips_clean_recording(fake, tmp_path):
    fake["audio"] = _speechlike(30) + 1e-4 * RNG.standard_normal(SR * 30).astype(np.float32)
    jid, j = _run(tmp_path, "auto")
    assert j["status"] == "done" and fake["cleaned"] == 0
    assert j["noise"] == {"mode": "auto", "snr": j["noise"]["snr"], "cleaned": False}


def test_auto_cleans_noisy_recording_for_asr(fake, tmp_path):
    fake["audio"] = _with_noise(_speechlike(30), 0)
    jid, j = _run(tmp_path, "auto")
    assert j["status"] == "done" and fake["cleaned"] == 1
    assert j["noise"]["cleaned"] is True and j["noise"]["snr"] < denoise.AUTO_SNR_DB
    assert fake["asr_input"] and not any(np.any(a) for a in fake["asr_input"])  # speech model heard the cleaned copy
    assert all(np.any(d) for d in fake["diar_input"])  # speaker separation got the original


def test_always_cleans_clean_recording(fake, tmp_path):
    jid, j = _run(tmp_path, "always")
    assert fake["cleaned"] == 1 and j["noise"]["cleaned"] is True


def test_missing_model_falls_back_to_original(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(denoise, "available", lambda: False)
    jid, j = _run(tmp_path, "always")
    assert j["status"] == "done" and fake["cleaned"] == 0 and j["noise"]["cleaned"] is False


def test_broken_cleaner_does_not_fail_job(fake, tmp_path, monkeypatch):
    def boom(samples, progress=None):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(denoise, "denoise", boom)
    jid, j = _run(tmp_path, "always")
    assert j["status"] == "done"
    assert all(np.any(a) for a in fake["asr_input"])


def test_playback_mp3_is_the_original(fake, tmp_path):
    jid, j = _run(tmp_path, "always")
    assert (store.job_path(jid) / "audio.mp3").read_bytes() == b"x"  # written by convert, never replaced


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path))
    api = bridge.Api(window_getter=lambda: None)
    assert api.get_settings()["denoise"] == "auto"
    assert api.set_settings({"denoise": "off"})["denoise"] == "off"
    assert api.set_settings({"denoise": "bogus"})["denoise"] == "off"
