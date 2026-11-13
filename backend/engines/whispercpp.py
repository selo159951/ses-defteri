"""whisper.cpp (Vulkan) engine: GPU transcription on AMD, Intel and NVIDIA cards.

Runs the official ``whisper-cli.exe`` as a subprocess; models are ggml files
from the official Hugging Face repo ggerganov/whisper.cpp.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .. import hardware, models, store
from ..merge import Word

HF_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_RUN_TIMEOUT_MIN = 600.0  # floor for one whisper-cli run (seconds)

_DEVICE_RE = re.compile(r"ggml_vulkan:\s*(\d+)\s*=\s*(.+)")
_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)\s*%")
_TIMING_RE = re.compile(r"whisper_print_timings:\s*(load|total) time\s*=\s*([\d.]+)\s*ms")
_SPECIAL_RE = re.compile(r"^\s*(\[_[A-Z]+_.*\]|<\|.*\|>|\[BLANK_AUDIO\]|\[[A-Z_]+\])\s*$")


# ---------- binary / devices ----------
def binary_dir() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "whispercpp"
    return Path(__file__).resolve().parents[2] / "vendor" / "whispercpp"


def binary_path() -> Path:
    return binary_dir() / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")


class WhisperCppError(RuntimeError):
    """The whisper.cpp run itself failed (binary, driver, model, empty output). The caller falls back to
    the processor. A stop request raised by a progress callback is NOT wrapped: it passes through as is."""


def parse_timings(lines) -> dict:
    """whisper_print_timings lines -> {"load": seconds, "total": seconds} (missing keys when not printed)."""
    out = {}
    for line in lines:
        m = _TIMING_RE.search(line)
        if m:
            out[m.group(1)] = float(m.group(2)) / 1000.0
    return out


def ggml_candidates(integrated: bool = True) -> tuple[str, ...]:
    """ggml files to look for, best first. Onboard graphics (2 GB of their own memory + shared RAM) get
    the quantized q5_0 file only; a real graphics card may also use the full-size file."""
    return ("large-v3-turbo-q5_0",) if integrated else ("large-v3-turbo-q5_0", "large-v3-turbo")


def find_model(model: str = "large-v3-turbo", integrated: bool = True) -> Path | None:
    """Downloaded ggml file for `model`, or None. Uses models.ggml_path (the downloader's API); when it
    does not exist (or says no) the Vulkan engine is simply not available. Nothing is downloaded here."""
    fn = getattr(models, "ggml_path", None)
    if not callable(fn):
        return None
    names = ggml_candidates(integrated) if model == "large-v3-turbo" else (model,)
    for n in names:
        try:
            p = fn(n)
        except Exception:
            p = None
        if p and Path(p).is_file():
            return Path(p)
    return None


def models_dir() -> Path:
    d = store.data_dir() / "models" / "ggml"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run_kwargs() -> dict:
    kw: dict = {"creationflags": _CREATE_NO_WINDOW}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
    return kw


def parse_devices(text: str) -> list[dict]:
    """Parse ``ggml_vulkan: 0 = AMD Radeon ... | uma: 0 | ...`` lines.

    Returns [{"index", "name", "vram_mb" (None when not printed), "integrated" (uma)}].
    """
    devs: list[dict] = []
    for line in text.splitlines():
        m = _DEVICE_RE.search(line)
        if not m:
            continue
        rest = m.group(2)
        name = rest.split("|")[0].strip()
        vram = None
        vm = re.search(r"(?:vram|memory|heap)[^0-9]*(\d+)\s*(MiB|MB|GiB|GB)", rest, re.I)
        if vm:
            vram = int(vm.group(1)) * (1024 if vm.group(2).lower().startswith("g") else 1)
        uma = re.search(r"uma:\s*(\d)", rest)
        devs.append({"index": int(m.group(1)), "name": name, "vram_mb": vram,
                     "integrated": bool(uma and uma.group(1) == "1")})
    return devs


_devices_cache: list[dict] | None = None


def list_devices(refresh: bool = False) -> list[dict]:
    """Vulkan devices as seen by whisper-cli (runs the binary once, cached)."""
    global _devices_cache
    if _devices_cache is not None and not refresh:
        return _devices_cache
    exe = binary_path()
    if not exe.is_file():
        return []
    devs: list[dict] = []
    try:
        # the backend registers its devices at startup; a dummy model makes the
        # run fail quickly after the ggml_vulkan device lines are printed.
        with tempfile.TemporaryDirectory() as td:
            dummy = Path(td) / "x.bin"
            dummy.write_bytes(b"lmgg" + b"\0" * 64)
            p = subprocess.run([str(exe), "-m", str(dummy), "-f", str(dummy)],
                               capture_output=True, text=True, errors="replace",
                               timeout=60, cwd=str(exe.parent), **_run_kwargs())
        devs = parse_devices((p.stdout or "") + "\n" + (p.stderr or ""))
    except (OSError, subprocess.SubprocessError):
        devs = []
    _devices_cache = devs
    return devs


def best_device(devs: list[dict] | None = None) -> dict | None:
    """Prefer a discrete GPU over an integrated one (whisper-cli defaults to device 0)."""
    devs = list_devices() if devs is None else devs
    if not devs:
        return None
    for d in devs:
        if not d.get("integrated"):
            return d
    return devs[0]


def available() -> tuple[bool, str]:
    exe = binary_path()
    if not exe.is_file():
        return False, f"whisper.cpp binary not found ({exe})"
    devs = list_devices()
    if not devs:
        return False, "no Vulkan GPU device found"
    return True, best_device(devs)["name"]


# ---------- models ----------
def model_file_name(model: str, vram_gb: float | None) -> str:
    """ggml file stem; quantized q5_0 on small GPUs (<4 GB)."""
    if model.endswith("-q5_0") or model.endswith("-q8_0"):
        return model
    if vram_gb is not None and vram_gb < 4:
        return f"{model}-q5_0"
    return model


def download_model(name: str, dest: Path, progress: Callable[[float], None] | None = None) -> None:
    url = HF_URL.format(name=name)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "SesDefteri"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
            if total and done != total:
                raise RuntimeError(f"incomplete download ({done}/{total} bytes)")
        os.replace(tmp, dest)
    except Exception as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError(f"could not download ggml model {name}: {e}") from e


# ---------- parsing ----------
def parse_progress(line: str) -> int | None:
    m = _PROGRESS_RE.search(line)
    return int(m.group(1)) if m else None


def _is_special(text: str) -> bool:
    return bool(_SPECIAL_RE.match(text))


def _spread_collapsed(words: list[Word], min_len: float = 0.02) -> None:
    """whisper.cpp token timestamps often collapse (several words with zero length at the
    same instant). Spread such runs over the gap up to the next word, weighted by length."""
    i, n = 0, len(words)
    while i < n:
        if words[i].end - words[i].start >= min_len:
            i += 1
            continue
        j = i
        while j < n and words[j].end - words[j].start < min_len:
            j += 1
        start = words[i].start
        nxt = words[j].start if j < n else None
        end = nxt if nxt is not None and nxt > start else start + 0.25 * (j - i)
        end = max(end, start + 0.05 * (j - i))
        total = sum(max(1, len(w.text.strip())) for w in words[i:j])
        t = start
        for w in words[i:j]:
            d = (end - start) * max(1, len(w.text.strip())) / total
            w.start, w.end = t, t + d
            t += d
        i = j


def words_from_json(data: dict) -> tuple[list[Word], str]:
    """Build words from whisper-cli ``-ojf`` JSON (token offsets in ms)."""
    words: list[Word] = []
    cur: Word | None = None
    for seg in data.get("transcription", []):
        for tok in seg.get("tokens", []):
            text = tok.get("text", "")
            if not text or _is_special(text):
                continue
            off = tok.get("offsets") or {}
            t0, t1 = off.get("from"), off.get("to")
            if t0 is None or t1 is None:
                continue
            t0, t1 = t0 / 1000.0, t1 / 1000.0
            if cur is None or text[0].isspace():
                if cur is not None and cur.text.strip():
                    words.append(cur)
                cur = Word(t0, max(t1, t0), text if text[0].isspace() else " " + text)
            else:
                cur.text += text
                cur.end = max(cur.end, t1)
    if cur is not None and cur.text.strip():
        words.append(cur)
    _spread_collapsed(words)
    lang = (data.get("result") or {}).get("language") or ""
    return words, lang


# ---------- engine ----------
class WhisperCppEngine:
    name = "whispercpp"

    def __init__(self) -> None:
        self.device = "cpu"
        self.extra_args: list[str] = []  # additional whisper-cli flags (e.g. ["-dtw", "large.v3.turbo"])
        self.device_index = 0
        self.device_name = ""
        self.model_path: Path | None = None
        self.model_name = ""
        self.last_timings: dict = {}  # {"load": s, "total": s} of the last run, from whisper-cli's own report

    def load(self, model: str = "large-v3-turbo", progress: Callable[[float], None] | None = None,
             vram_gb: float | None = None) -> None:
        exe = binary_path()
        if not exe.is_file():
            raise WhisperCppError(f"whisper.cpp binary not found: {exe}")
        best = best_device()
        if not best:
            raise WhisperCppError("no Vulkan GPU device found")
        self.device = "vulkan"
        self.device_index, self.device_name = best["index"], best["name"]
        path = find_model(model, bool(best.get("integrated", True)))
        if path is None:
            raise WhisperCppError("ggml model file is not downloaded")
        self.model_path = path
        self.model_name = path.stem.removeprefix("ggml-")

    def transcribe(self, samples: np.ndarray, duration: float,
                   progress: Callable[[float], None] | None = None) -> tuple[list[Word], str]:
        if self.model_path is None:
            raise RuntimeError("model not loaded")
        exe = binary_path()
        threads = hardware.whisper_threads()
        pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
        with tempfile.TemporaryDirectory(prefix="mt_wcpp_") as td:
            wav = Path(td) / "in.wav"
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(pcm.tobytes())
            out_base = Path(td) / "out"
            from .. import asr

            mode = asr.language_mode()  # whisper.cpp has no per-window detection: "mixed" is detected per part, like "auto"
            cmd = [str(exe), "-m", str(self.model_path), "-f", str(wav), "-l", mode if mode not in ("auto", "mixed") else "auto",
                   "-ojf", "-of", str(out_base), "-t", str(threads), "--print-progress",
                   "-mc", "0"]  # no previous-text conditioning (avoids repetition loops)
            from .. import glossary

            hot = glossary.hotwords()
            if hot:
                cmd += ["--prompt", hot]  # the names the user cares about, written as the model should spell them
            cmd += self.extra_args
            if self.device == "cpu":
                cmd.append("-ng")
            else:
                cmd += ["-dev", str(self.device_index)]
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        text=True, errors="replace", cwd=str(exe.parent), **_run_kwargs())
            except OSError as e:
                raise WhisperCppError(f"cannot start whisper-cli: {e}") from e
            tail: list[str] = []
            stopped: list[BaseException] = []  # raised by the progress callback (stop / cancel request)

            def pump() -> None:
                assert proc.stderr is not None
                for line in proc.stderr:
                    p = parse_progress(line)
                    if p is not None:
                        if progress and not stopped:
                            try:
                                progress(min(1.0, p / 100.0))
                            except BaseException as e:  # a stop request: end the run now, re-raise below
                                stopped.append(e)
                                try:
                                    proc.kill()
                                except OSError:
                                    pass
                    else:
                        tail.append(line.rstrip())
                        del tail[:-60]

            t = threading.Thread(target=pump, daemon=True)
            t.start()
            timeout = max(_RUN_TIMEOUT_MIN, duration * 2.0)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise WhisperCppError(f"whisper-cli timed out after {timeout:.0f}s")
            t.join(5)
            if stopped:
                raise stopped[0]
            if proc.returncode != 0:
                raise WhisperCppError(f"whisper-cli failed (exit {proc.returncode}):\n" + "\n".join(tail[-8:]))
            jf = Path(str(out_base) + ".json")
            if not jf.is_file():
                raise WhisperCppError("whisper-cli produced no JSON output")
            try:
                data = json.loads(jf.read_text("utf-8", errors="replace"))
            except ValueError as e:
                raise WhisperCppError(f"whisper-cli wrote unreadable JSON: {e}") from e
            self.last_timings = parse_timings(tail)
        if progress:
            progress(1.0)
        return words_from_json(data)
