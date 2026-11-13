"""Fastest engine for THIS PC: a short first-use self-test, remembered with a hardware fingerprint.

The simple edition runs on one known kind of PC (Ryzen laptop with onboard Radeon graphics) but must also
work, and be as fast as it can, on any other. Instead of guessing whether whisper.cpp/Vulkan on the
graphics chip beats CTranslate2 on the processor, the first transcription runs both for ~25 s on a bundled
sample, keeps the faster one that also produced sane text, and stores the verdict in settings.json next to
a fingerprint of the hardware (a different PC or a changed graphics card tests again).

Everything that decides is a small pure function (unit-tested with fake engines); `run_selftest` takes the
engine factories, so no model is loaded in the tests. Nothing here may raise into a job: any engine error
means "use the processor".
"""
from __future__ import annotations

import difflib
import gc
import re
import sys
import time
import unicodedata
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from . import available_engines, choose
from .. import hardware

TUNING_VERSION = 2          # bump to make every PC test again (new engine build, changed rules)
SAMPLE_SECONDS = 25.0
PART_SECONDS = 300.0        # a recording is transcribed in parts of at most 5 minutes (chunking.TARGET)
WIN_MARGIN = 0.85           # Vulkan must be at least 15 % faster than the processor to be chosen
MIN_SIMILARITY = 0.55       # its text must resemble what the processor wrote (garbage / hallucination check)
CPU = "ct2-cpu"
VULKAN = "whispercpp"

RETRY_REASONS = ("vulkan_failed", "runtime_failure", "selftest_error")
RETRY_AFTER = 14 * 86400    # seconds before a remembered Vulkan failure is tested again

NOTE_SELFTEST = "selftest"  # job field stage_note while the test runs (the page shows a Turkish sentence)


# ---------------- sample ----------------
def sample_path() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "assets" / "speedtest.wav"
    return Path(__file__).resolve().parents[2] / "assets" / "speedtest.wav"


def load_sample(path: Path | None = None) -> tuple[np.ndarray, float] | None:
    """(float32 16 kHz mono samples, seconds) of the bundled speech sample (assets/speedtest.wav, synthetic
    text-to-speech), the first 25 s of it. None if it cannot be read."""
    try:
        with wave.open(str(path or sample_path()), "rb") as w:
            if w.getframerate() != 16000 or w.getsampwidth() != 2 or w.getnchannels() != 1:
                return None
            n = min(w.getnframes(), int(SAMPLE_SECONDS * 16000))
            pcm = np.frombuffer(w.readframes(n), dtype="<i2")
    except (OSError, EOFError, wave.Error):
        return None
    if len(pcm) < 16000 * 5:
        return None
    return pcm.astype(np.float32) / 32768.0, len(pcm) / 16000.0


# ---------------- fingerprint and verdict storage ----------------
def fingerprint(hw: dict, ggml_name: str = "") -> str:
    """Same string = same PC for our purposes: CPU model + core count, graphics chips (+memory), speech file."""
    cpu = hw.get("cpu") or {}
    gpus = ";".join(f"{g.get('name', '')}/{g.get('vram_gb', 0)}" for g in hw.get("gpus", []))
    return f"v{TUNING_VERSION}|{cpu.get('name', '')}|{cpu.get('physical') or cpu.get('cores')}|{gpus}|{ggml_name}"


def stored_pick(settings: dict, fp: str) -> dict | None:
    """The remembered verdict if it was made on this hardware, else None (= test again)."""
    pick = settings.get("engine_pick")
    if isinstance(pick, dict) and pick.get("fingerprint") == fp and pick.get("winner") in (CPU, VULKAN):
        if pick.get("reason") in RETRY_REASONS and time.time() - float(pick.get("at") or 0) > RETRY_AFTER:
            return None  # a failure may have been temporary (driver update, file just downloaded): look again
        return pick
    return None


def make_pick(fp: str, winner: str, reason: str, **extra) -> dict:
    return {"fingerprint": fp, "winner": winner, "reason": reason, "at": int(time.time()), **extra}


# ---------------- judging a run ----------------
def _words(text: str) -> list[str]:
    """Lower-case words without accents (Turkish dotted/dotless i and s/g with marks may differ between engines)."""
    t = unicodedata.normalize("NFKD", (text or "").lower().replace("\u0131", "i"))
    return re.findall(r"\w+", "".join(c for c in t if not unicodedata.combining(c)))


def similarity(a: str, b: str) -> float:
    """0..1 word-level resemblance of two transcripts."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def looks_like_garbage(text: str) -> bool:
    """Empty, or a loop / junk: very few distinct words, or one word repeated, or mostly non-letters."""
    w = _words(text)
    if len(w) < 5:
        return True
    if len(set(w)) / len(w) < 0.25:
        return True
    letters = sum(c.isalpha() for c in text)
    return letters < 0.5 * max(1, len(text.replace(" ", "")))


def projected_rtf(wall: float, audio: float, load: float | None) -> float:
    """Seconds of work per second of audio over a real 5 minute part. whisper-cli reloads its model in
    every call, so that fixed cost is spread over a whole part instead of the short sample."""
    if audio <= 0:
        return float("inf")
    if load is None or load < 0 or load > wall:
        return wall / audio
    return (wall - load) / audio + load / PART_SECONDS


def decide(results: dict) -> tuple[str, str]:
    """results: {"ct2-cpu": run, "whispercpp": run}; run = {"ok", "rtf", "text", "error"}. -> (winner, reason).
    The processor is the default; Vulkan has to prove itself."""
    cpu, vk = results.get(CPU) or {}, results.get(VULKAN)
    if not vk:
        return CPU, "vulkan_not_tested"
    if not vk.get("ok"):
        return CPU, "vulkan_failed"
    if looks_like_garbage(vk.get("text", "")):
        return CPU, "vulkan_empty_or_garbage"
    if not cpu.get("ok") or looks_like_garbage(cpu.get("text", "")):
        # the processor run is no reference: only trust Vulkan if the processor really crashed
        return (VULKAN, "cpu_failed") if not cpu.get("ok") else (CPU, "no_reference_text")
    if similarity(cpu["text"], vk["text"]) < MIN_SIMILARITY:
        return CPU, "vulkan_text_differs"
    if vk["rtf"] <= WIN_MARGIN * cpu["rtf"]:
        return VULKAN, "vulkan_faster"
    return CPU, "cpu_faster"


# ---------------- running the test ----------------
def _release(*objs) -> None:
    del objs
    gc.collect()


def _text(words) -> str:
    return "".join(w.text for w in words)


def run_selftest(model: str, factories: dict[str, Callable[[], object]], sample: tuple[np.ndarray, float],
                 clock: Callable[[], float] = time.perf_counter) -> tuple[dict, object | None]:
    """Run the processor engine and (when a factory exists) the Vulkan engine on the sample.

    factories: {"ct2-cpu": () -> engine, "whispercpp": () -> engine}. Returns (results, ct2_engine_or_None);
    the loaded processor engine is handed back so a CPU win costs no second model load. Never raises."""
    samples, dur = sample
    results: dict = {}
    keep = None
    noop = lambda p: None  # noqa: E731

    def run_once(eng) -> tuple[float, str]:
        t0 = clock()
        words, _ = eng.transcribe(samples, dur, noop)
        return clock() - t0, _text(words)

    # --- processor ---
    try:
        eng = factories[CPU]()
        eng.load(model)
        wall, text = run_once(eng)
        results[CPU] = {"ok": True, "rtf": wall / dur, "text": text, "error": ""}
        keep = eng
    except Exception as e:  # noqa: BLE001 - a broken processor engine must not stop the verdict
        results[CPU] = {"ok": False, "rtf": float("inf"), "text": "", "error": f"{type(e).__name__}: {e}"}
    # --- graphics chip ---
    if VULKAN in factories:
        try:
            veng = factories[VULKAN]()
            veng.load(model)
            best, text, n = None, "", 0
            cpu_rtf = results[CPU]["rtf"]
            for n in (1, 2):
                wall, text = run_once(veng)
                rtf = projected_rtf(wall, dur, (getattr(veng, "last_timings", None) or {}).get("load"))
                if best is None or rtf < best:
                    best = rtf
                if best < 0.5 * cpu_rtf or best > 3.0 * cpu_rtf or looks_like_garbage(text):
                    break  # clear verdict after one run (the first run also compiles GPU shaders)
            results[VULKAN] = {"ok": True, "rtf": best, "text": text, "error": "", "runs": n}
            _release(veng)
        except Exception as e:  # noqa: BLE001 - driver crash, missing runtime, bad model file ...
            results[VULKAN] = {"ok": False, "rtf": float("inf"), "text": "", "error": f"{type(e).__name__}: {e}"}
    winner, reason = decide(results)
    if winner != CPU and keep is not None:
        keep = None  # free the processor model: the Vulkan engine will run
        gc.collect()
    return {"winner": winner, "reason": reason, "runs": results}, keep


def summary(res: dict) -> dict:
    """The part of a self-test worth keeping in settings.json (no transcripts)."""
    out = {}
    for k, r in res["runs"].items():
        out[k] = {"ok": r["ok"], "rtf": None if r["rtf"] == float("inf") else round(r["rtf"], 3),
                  "error": r.get("error", "")[:200]}
    return out


# ---------------- the plan ----------------
def vulkan_candidate(hw: dict, wcpp: tuple[bool, str] | None = None, ggml_present: bool | None = None) -> bool:
    """Can the Vulkan engine be tried at all here? Needs a GPU, the Vulkan runtime, the whisper.cpp
    binary with a device, and the downloaded ggml file."""
    ok = {e["id"]: e["ok"] for e in available_engines(hw, (False, ""), wcpp)}
    if not ok.get(VULKAN):
        return False
    if ggml_present is None:
        from . import whispercpp

        ggml_present = whispercpp.find_model("large-v3-turbo", True) is not None
    return bool(ggml_present)


def choose_tuned(hw: dict, settings: dict, cuda: tuple[bool, str] | None = None,
                 wcpp: tuple[bool, str] | None = None, ggml_present: bool | None = None,
                 fp: str | None = None) -> dict:
    """Plan for the simple edition. CUDA when it really works (never in the packaged app); otherwise the
    processor, or Vulkan when the remembered self-test says it is faster on this PC. With no verdict yet the
    plan is the processor with selftest=True: asr.load_model then runs the test first.
    Same keys as engines.choose, plus selftest (bool) and pick (the stored verdict or None)."""
    if fp is None:
        gname = ""
        if ggml_present is None:
            from . import whispercpp

            m = whispercpp.find_model("large-v3-turbo", True)
            gname = m.name if m else ""
        fp = fingerprint(hw, gname)
    base = choose(hw, {"engine": "auto"}, cuda, wcpp)
    if base["engine"] == "ct2" and base["device"] == "cuda":
        return dict(base, selftest=False, pick=None, threads=None)
    plan = {"engine": "ct2", "device": "cpu", "compute": "int8", "requested": "auto", "fallback_from": None,
            "selftest": False, "pick": None, "threads": hardware.cpu_threads(hw.get("cpu", {}).get("physical"))}
    if not vulkan_candidate(hw, wcpp, ggml_present):
        return dict(plan, reason="auto_cpu")
    pick = stored_pick(settings, fp)
    if pick is None:
        return dict(plan, reason="selftest_pending", selftest=True, fingerprint=fp)
    if pick["winner"] == VULKAN:
        return dict(plan, engine="whispercpp", device="vulkan", compute="fp16", reason="selftest_vulkan",
                    pick=pick, fingerprint=fp, threads=hardware.whisper_threads())
    return dict(plan, reason="selftest_cpu", pick=pick, fingerprint=fp)
