"""Offline noise cleanup before transcription (sherpa-onnx GTCRN speech denoiser, ~0.5 MB, runs on CPU).

Nothing here touches the network: the model file ships in models/ next to the speaker models.
The cleaned audio is used for transcription only; the playback mp3 always keeps the original.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import numpy as np

SR = 16000
MODEL = "gtcrn_simple.onnx"
MODES = ("off", "auto", "always")
# Off by default: on the measurements in docs/noise-cleanup.md the speech model is already robust to noise and the
# cleaner changed the text for the worse about as often as for the better.
DEFAULT_MODE = "off"
# Auto mode cleans a recording only when its estimated speech-to-noise ratio is below this (dB): only
# really bad recordings, where there is little left to lose.
AUTO_SNR_DB = 8.0
BLOCK = 60 * SR       # the model runs on blocks of this many samples ...
FADE = SR             # ... that overlap by this much and are cross-faded
THREADS = 4

_lock = threading.Lock()
_engine = None


def model_path() -> Path:
    from . import diarize

    return diarize.models_dir() / MODEL


def available() -> bool:
    return model_path().exists()


def normalize_mode(value) -> str:
    return value if value in MODES else DEFAULT_MODE


# ---------------- how noisy is the recording? ----------------
def estimate_snr(samples: np.ndarray) -> float:
    """Rough speech-to-noise ratio in dB from short-frame energies: the loud frames are taken as speech
    and the quiet ones as noise floor. Cheap (a few ms per minute) and only meant to rank recordings."""
    x = np.asarray(samples, dtype=np.float32)
    n = 400  # 25 ms frames, no overlap
    frames = len(x) // n
    if frames < 20:
        return 99.0
    e = np.mean(x[: frames * n].reshape(frames, n) ** 2, axis=1) + 1e-12
    db = 10 * np.log10(e)
    floor, speech = np.percentile(db, 10), np.percentile(db, 90)
    if speech < -70:  # silence
        return 99.0
    return float(speech - floor)


def should_denoise(mode: str, samples: np.ndarray) -> tuple[bool, float]:
    """(clean it?, estimated SNR dB). Off never, Always always, Auto only a recording that looks noisy."""
    mode = normalize_mode(mode)
    if mode == "off":
        return False, float("nan")
    snr = estimate_snr(samples)
    if mode == "always":
        return True, snr
    return snr < AUTO_SNR_DB, snr


# ---------------- the cleaner ----------------
def _load():
    global _engine
    with _lock:
        if _engine is None:
            import sherpa_onnx as so

            cfg = so.OfflineSpeechDenoiserConfig(model=so.OfflineSpeechDenoiserModelConfig(
                gtcrn=so.OfflineSpeechDenoiserGtcrnModelConfig(model=str(model_path())), num_threads=THREADS))
            _engine = so.OfflineSpeechDenoiser(cfg)
        return _engine


def denoise(samples: np.ndarray, progress: Callable[[float], None] | None = None) -> np.ndarray:
    """Return cleaned samples of exactly the same length (float32, 16 kHz). The recording is cut into
    overlapping blocks so memory stays small; the overlaps are cross-faded. `progress(p)` may raise to stop."""
    eng = _load()
    n = len(samples)
    out = np.zeros(n, dtype=np.float32)
    step = BLOCK - FADE
    starts = list(range(0, max(n - FADE, 1), step)) or [0]
    for i, a in enumerate(starts):
        b = min(a + BLOCK, n)
        res = eng.run(np.ascontiguousarray(samples[a:b], dtype=np.float32), SR)
        y = np.asarray(res.samples, dtype=np.float32)
        if len(y) < b - a:
            y = np.pad(y, (0, b - a - len(y)))
        y = y[: b - a].copy()
        if i > 0:  # fade in over the overlap with the previous block
            m = min(FADE, len(y))
            y[:m] *= np.linspace(0.0, 1.0, m, dtype=np.float32)
        if b < n:  # fade out where the next block takes over
            m = min(FADE, len(y))
            y[-m:] *= np.linspace(1.0, 0.0, m, dtype=np.float32)
        out[a:b] += y
        if progress:
            progress(min(1.0, b / n))
        if b >= n:
            break
    return out
