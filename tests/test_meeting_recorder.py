"""Meeting recording (computer sound + microphone) and live text, with fake sound devices. No real audio."""
import json
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import meeting_recorder as mr  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))
    mr._active.clear()


class FakeDev:
    """soundcard-like device: a sine tone (or silence), delivered ~20x faster than real time."""

    def __init__(self, freq=440.0, amp=0.3, fail_after=None, stereo=False):
        self.freq, self.amp, self.fail_after, self.stereo = freq, amp, fail_after, stereo
        self.calls = 0

    def recorder(self, samplerate, channels, blocksize=None):
        dev = self

        class R:
            pos = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def record(self, numframes):
                dev.calls += 1
                if dev.fail_after is not None and dev.calls > dev.fail_after:
                    raise OSError("device unplugged")
                time.sleep(numframes / samplerate / 20)
                t = (np.arange(numframes) + self.pos) / samplerate
                self.pos += numframes
                x = (dev.amp * np.sin(2 * np.pi * dev.freq * t)).astype(np.float32)
                return np.stack([x, x], 1) if channels == 2 else x[:, None]
        return R()


def wait_for(cond, timeout=10.0):
    t0 = time.time()
    while not cond():
        if time.time() - t0 > timeout:
            raise AssertionError("timed out")
        time.sleep(0.02)


def wav_seconds(p: Path) -> float:
    with wave.open(str(p)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return w.getnframes() / 16000


# ---------------------------------------------------------------- signal
def test_downsampler_keeps_speech_and_removes_high_tones():
    ds = mr.Downsampler()
    t = np.arange(48000) / 48000
    speech = np.concatenate([ds(x) for x in np.split((0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32), 10)])
    assert len(speech) == 16000
    assert abs(float(np.sqrt(np.mean(speech[200:] ** 2))) - 0.5 / np.sqrt(2)) < 0.02
    hi = mr.Downsampler()(0.5 * np.sin(2 * np.pi * 12000 * t).astype(np.float32))
    assert float(np.sqrt(np.mean(hi[200:] ** 2))) < 0.02  # would fold back to 4 kHz without the filter


def test_downsampler_block_borders_have_no_clicks():
    t = np.arange(48000) / 48000
    x = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    whole = mr.Downsampler()(x)
    ds = mr.Downsampler()
    parts = np.concatenate([ds(b) for b in np.array_split(x, 37)])  # odd block sizes
    assert np.allclose(whole, parts, atol=1e-5)


def test_mix_lifts_quiet_microphone_and_limits_peaks():
    loud = np.full(16000, 0.9, np.float32)
    quiet = np.full(8000, 0.01, np.float32)
    m = mr.mix([loud, quiet])
    assert len(m) == 16000 and float(np.abs(m).max()) <= 0.95 + 1e-6
    assert m[0] > m[-1]  # the part with the (lifted) mic is louder than the part without


def test_quiet_cut_finds_the_pause():
    x = np.random.default_rng(1).normal(0, 0.3, 16000 * 10).astype(np.float32)
    x[16000 * 8: int(16000 * 8.3)] = 0  # a pause at 8.0-8.3 s
    c = mr.quiet_cut(x)
    assert 16000 * 8 <= c <= int(16000 * 8.3)


# ---------------------------------------------------------------- recorder
def test_record_stop_gives_one_wav_with_both_sources():
    rec = mr.MeetingRecorder({"system": FakeDev(440, stereo=True), "mic": FakeDev(220, 0.05)}).start()
    wait_for(lambda: rec.seconds() >= 2)
    st = rec.status()
    assert st["active"] and set(st["levels"]) == {"system", "mic"} and st["levels"]["system"] > 0.1
    wav = rec.stop()
    assert wav.exists() and wav.suffix == ".wav" and wav.name.startswith("Toplantı ")
    assert wav_seconds(wav) >= 2
    assert not list(wav.parent.glob("*.pcm"))
    assert json.loads((wav.parent / "meta.json").read_text("utf-8"))["state"] == "mixed"


def test_pause_keeps_nothing():
    rec = mr.MeetingRecorder({"mic": FakeDev()}).start()
    wait_for(lambda: rec.seconds() >= 1)
    rec.pause(True)
    time.sleep(0.2)
    before = rec.seconds()
    time.sleep(0.5)
    assert rec.seconds() == before
    rec.pause(False)
    wait_for(lambda: rec.seconds() > before + 0.5)
    rec.cancel()
    assert not rec.folder.exists()


def test_one_device_failing_does_not_stop_the_other():
    rec = mr.MeetingRecorder({"system": FakeDev(fail_after=3), "mic": FakeDev()}).start()
    wait_for(lambda: "system" in rec.errors)
    wait_for(lambda: rec.samples["mic"] > rec.samples["system"] + 16000)
    assert "unplugged" in rec.errors["system"]
    assert wav_seconds(rec.stop()) >= 1


def test_empty_recording_is_refused():
    rec = mr.MeetingRecorder({"mic": FakeDev()})
    with pytest.raises(ValueError):
        rec.stop()


def test_crash_leaves_a_recoverable_recording():
    rec = mr.MeetingRecorder({"mic": FakeDev()}).start()
    wait_for(lambda: rec.seconds() >= 1.5)
    assert mr.leftovers() == []  # not while it is being recorded
    rec._stop.set()  # "crash": threads end, nothing mixed
    for t in rec._threads:
        t.join()
    mr._active.clear()
    left = mr.leftovers()
    assert len(left) == 1 and left[0]["seconds"] >= 1.5
    wav = mr.recover(left[0]["folder"])
    assert wav_seconds(wav) >= 1.5
    assert mr.leftovers()[0]["folder"] == left[0]["folder"]  # mixed but not processed yet: still offered
    assert mr.recover(left[0]["folder"]) == wav
    mr.discard(left[0]["folder"])
    assert mr.leftovers() == []


def test_discard_cannot_leave_the_recordings_folder(tmp_path):
    keep = mr.recordings_dir().parent / "jobs"
    keep.mkdir(exist_ok=True)
    mr.discard("../jobs")
    assert keep.exists()


# ---------------------------------------------------------------- live text
def speech(seconds, pause_at=None):
    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.2, int(16000 * seconds)).astype(np.float32)
    if pause_at:
        x[int(16000 * pause_at): int(16000 * (pause_at + 0.3))] = 0
    return x


def test_live_text_writes_lines_cut_at_pauses():
    seen = []

    def tr(samples, dur):
        seen.append(dur)
        return f"parça {len(seen)}"
    lw = mr.LiveWriter(tr, every=4.0).start(["mic"])
    x = speech(10, pause_at=4.6)
    for block in np.array_split(x, 100):
        lw.feed("mic", block)
    wait_for(lambda: len(lw.lines) >= 2)
    lw.stop()
    assert lw.lines[0]["text"] == "parça 1" and lw.lines[0]["start"] == 0
    assert 4.6 <= seen[0] <= 4.95  # cut inside the pause, not at exactly 4 s
    assert lw.lines[1]["start"] == lw.lines[0]["end"]


def test_live_text_mixes_both_sources():
    got = []
    lw = mr.LiveWriter(lambda s, d: got.append(len(s)) or "x", every=2.0).start(["system", "mic"])
    lw.feed("system", speech(3))
    time.sleep(0.3)
    assert got == []  # waits for the microphone too
    lw.feed("mic", speech(3))
    wait_for(lambda: got)
    lw.stop()


def test_live_text_reports_slow_state(monkeypatch):
    clock = iter(range(0, 1000, 20))  # every transcription "takes" 20 s
    monkeypatch.setattr(mr.time, "time", lambda: next(clock))
    states = []
    lw = mr.LiveWriter(lambda s, d: "x", every=1.0, on_stop=states.append).start(["mic"])
    for _ in range(4):
        lw.feed("mic", speech(1.2))
    wait_for_real = time.monotonic() + 10
    while lw.state == "running" and time.monotonic() < wait_for_real:
        lw.feed("mic", speech(1.2))
        time.sleep(0.05)
    assert lw.state == "slow"
    t0 = time.monotonic()
    while not states and time.monotonic() - t0 < 5:
        time.sleep(0.02)
    assert states == ["slow"]


def test_live_text_error_stops_cleanly():
    def boom(s, d):
        raise RuntimeError("model missing")
    lw = mr.LiveWriter(boom, every=1.0).start(["mic"])
    lw.feed("mic", speech(1.5))
    deadline = time.monotonic() + 5
    while lw.state == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert lw.state == "error" and "model missing" in lw.error
