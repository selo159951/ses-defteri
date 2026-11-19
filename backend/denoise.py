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
# Automatic by default: on the measurements in docs/noise-cleanup.md the cleaner helps some recordings and hurts others,
# so a noisy-looking recording is not decided silently: the user hears an excerpt both ways and the answers teach the threshold.
DEFAULT_MODE = "auto"
# Auto mode cleans a recording only when its estimated speech-to-noise ratio is below this (dB) - until the
# user's answers move it (see learned_threshold).
AUTO_SNR_DB = 8.0
THRESH_MIN, THRESH_MAX = 0.0, 20.0   # the learned threshold stays inside this range (dB)
ASK_BAND = 3.0          # recordings within +-3 dB of the threshold are always asked about
FULL_TRUST = 6          # this many answers before the learned value is used in full
KEEP_ANSWERS = 40       # only the latest answers count
EXCERPT_SECS = 12       # length of the A/B excerpt
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


def should_denoise(mode: str, samples: np.ndarray, threshold: float | None = None) -> tuple[bool, float]:
    """(clean it?, estimated SNR dB). Off never, Always always, Auto only a recording that looks noisy
    (below the learned threshold)."""
    mode = normalize_mode(mode)
    if mode == "off":
        return False, float("nan")
    snr = estimate_snr(samples)
    if mode == "always":
        return True, snr
    return snr < (current_threshold() if threshold is None else threshold), snr


# ---------------- learning the threshold from the user's answers ----------------
def _clamp(x: float) -> float:
    return max(THRESH_MIN, min(THRESH_MAX, float(x)))


def answers() -> list[tuple[float, bool]]:
    """[(snr, chose_cleaned)] in the order given, from the settings file."""
    from . import asr

    out = []
    for a in asr.get_settings().get("denoise_answers") or []:
        try:
            out.append((float(a[0]), bool(a[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out[-KEEP_ANSWERS:]


def learned_threshold(ans: list[tuple[float, bool]]) -> float:
    """Midpoint between the highest SNR the user wanted cleaned and the lowest SNR the user wanted left alone.
    With answers on one side only, the threshold is pushed just past the extreme answer (never back toward
    the other side of the default). It moves from 8 dB only gradually: full weight after FULL_TRUST answers."""
    if not ans:
        return AUTO_SNR_DB
    cleaned = [s for s, c in ans if c]
    original = [s for s, c in ans if not c]
    if cleaned and original:
        raw = (max(cleaned) + min(original)) / 2
    elif cleaned:
        raw = max(AUTO_SNR_DB, max(cleaned) + 1.5)
    else:
        raw = min(AUTO_SNR_DB, min(original) - 1.5)
    w = min(1.0, len(ans) / FULL_TRUST)
    return _clamp(AUTO_SNR_DB + (_clamp(raw) - AUTO_SNR_DB) * w)


def current_threshold() -> float:
    return learned_threshold(answers())


def record_choice(snr: float, cleaned: bool) -> None:
    from . import asr

    keep = [[round(s, 1), c] for s, c in answers()] + [[round(float(snr), 1), bool(cleaned)]]
    asr.set_setting("denoise_answers", keep[-KEEP_ANSWERS:])


def reset_learning() -> None:
    from . import asr

    asr.set_setting("denoise_answers", [])


def should_ask(snr: float, ans: list[tuple[float, bool]], threshold: float, enabled: bool = True) -> bool:
    """Ask about a recording near the threshold (both sides, so the answers teach in both directions) and about a
    noisier one - unless the last three answers far below the threshold were all "clean it"."""
    if not enabled:
        return False
    if abs(snr - threshold) <= ASK_BAND:
        return True
    if snr > threshold:
        return False  # clearly clean: left alone, nothing to ask
    far = [c for s, c in ans if s < threshold - ASK_BAND]
    return not (len(far) >= 3 and all(far[-3:]))


# ---------------- the A/B excerpt ----------------
def pick_excerpt(samples: np.ndarray, secs: float = EXCERPT_SECS) -> tuple[int, int]:
    """Sample range of about `secs` seconds that contains speech and is as noisy as the recording gets
    (highest noise floor among windows that are at least 40 % speech), so the difference is easy to hear."""
    x = np.asarray(samples, dtype=np.float32)
    want = int(secs * SR)
    if len(x) <= want:
        return 0, len(x)
    n = 400
    frames = len(x) // n
    db = 10 * np.log10(np.mean(x[: frames * n].reshape(frames, n) ** 2, axis=1) + 1e-12)
    floor, loud = np.percentile(db, 10), np.percentile(db, 90)
    speech = db > floor + (loud - floor) / 2
    w = want // n
    step = max(40, (frames - w) // 200)
    best, best_score = None, None
    for a in range(0, frames - w + 1, step):
        frac = float(speech[a:a + w].mean())
        score = (frac >= 0.4, float(np.percentile(db[a:a + w], 10)) if frac >= 0.4 else frac)
        if best_score is None or score > best_score:
            best, best_score = a, score
    a = (best or 0) * n
    return a, min(a + want, len(x))


def make_excerpt(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(original, cleaned) of the same short excerpt; the cleaned one is brought to the loudness of the original
    so that the comparison is about noise, not volume."""
    a, b = pick_excerpt(samples)
    orig = np.ascontiguousarray(samples[a:b], dtype=np.float32)
    clean = np.asarray(denoise(orig), dtype=np.float32)
    ro, rc = float(np.sqrt(np.mean(orig ** 2)) + 1e-9), float(np.sqrt(np.mean(clean ** 2)) + 1e-9)
    clean = np.clip(clean * min(4.0, ro / rc), -1.0, 1.0)
    return orig, clean


def write_wav(path, samples: np.ndarray) -> None:
    import wave

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


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
