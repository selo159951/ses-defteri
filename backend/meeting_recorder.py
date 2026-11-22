"""Record a meeting from inside the app: the computer's sound (Teams / Meet / Zoom, everything the speakers play)
and the microphone, at the same time.

- Each source is captured in its own thread (soundcard, WASAPI loopback for the speakers), turned into 16 kHz mono
  and appended to its own raw file in %APPDATA%\\SesDefteriBasit\\recordings\\<time>\\ every 0.1 s. A crash or power cut
  loses at most a moment: the next start offers to recover the recording.
- Stop mixes the two tracks into one WAV and queues it like a dropped file (speakers, names, analysis as usual).
- Optional live text (main edition): see LiveWriter. It is only a preview; the full processing runs after Stop.
- Nothing is sent anywhere; the recording stays in the data folder until it is processed.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import store

SR = 16000            # what the pipeline and the speech model use
CAP_SR = 48000        # what Windows devices give in shared mode; 3:1 down to 16 kHz
BLOCK = 4800          # 0.1 s at 48 kHz
SOURCES = ("system", "mic")


def recordings_dir() -> Path:
    d = store.data_dir() / "recordings"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- devices
def list_mics() -> list[dict]:
    try:
        import soundcard as sc

        default = sc.default_microphone().id
        return [{"id": m.id, "name": m.name, "default": m.id == default} for m in sc.all_microphones()]
    except Exception:
        return []


def open_devices(system: bool = True, mic: bool = True, mic_id: str | None = None) -> dict:
    """{"system": device, "mic": device} with what this PC has; a missing one is left out."""
    import soundcard as sc

    out = {}
    if system:
        try:
            out["system"] = sc.get_microphone(sc.default_speaker().id, include_loopback=True)
        except Exception:
            pass
    if mic:
        try:
            out["mic"] = sc.get_microphone(mic_id) if mic_id else sc.default_microphone()
        except Exception:
            try:
                out["mic"] = sc.default_microphone()
            except Exception:
                pass
    return out


# ---------------------------------------------------------------- signal helpers
_TAPS = None


def _lowpass_taps() -> np.ndarray:
    """Windowed-sinc low-pass at 7.2 kHz for 48 -> 16 kHz (keeps speech, removes what would fold back)."""
    global _TAPS
    if _TAPS is None:
        n = np.arange(-32, 33)
        fc = 7200 / CAP_SR
        h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(len(n))
        _TAPS = (h / h.sum()).astype(np.float32)
    return _TAPS


class Downsampler:
    """48 kHz blocks in, 16 kHz out, without clicks at block borders."""

    def __init__(self):
        self.tail = np.zeros(64, np.float32)
        self.phase = 0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.float32)
        if x.ndim == 2:
            x = x.mean(axis=1)
        buf = np.concatenate([self.tail, x])
        y = np.convolve(buf, _lowpass_taps(), mode="valid")  # len = len(x) + 64 - 64 = len(x)... aligned to buf[64:]
        self.tail = buf[-64:]
        out = y[self.phase::3]
        self.phase = (self.phase - len(y)) % 3
        return out


def to_int16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def read_pcm(path: Path) -> np.ndarray:
    if not path.exists():
        return np.zeros(0, np.float32)
    data = path.read_bytes()
    data = data[: len(data) // 2 * 2]
    return np.frombuffer(data, "<i2").astype(np.float32) / 32768.0


def mix(tracks: list[np.ndarray]) -> np.ndarray:
    """Sum the tracks (padded to the longest), each brought to a similar loudness so a quiet microphone is not lost
    under the meeting app's sound, then keep the peak under 0.95."""
    tracks = [t for t in tracks if len(t)]
    if not tracks:
        return np.zeros(0, np.float32)
    n = max(len(t) for t in tracks)
    out = np.zeros(n, np.float32)
    for t in tracks:
        rms = float(np.sqrt(np.mean(t.astype(np.float64) ** 2))) if len(t) else 0.0
        gain = min(8.0, 0.08 / rms) if rms > 1e-4 else 1.0  # very quiet track: lift, never more than 8x
        out[: len(t)] += t * gain
    peak = float(np.abs(out).max()) if n else 0.0
    if peak > 0.95:
        out *= 0.95 / peak
    return out


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(to_int16(samples))


# ---------------------------------------------------------------- recorder
class MeetingRecorder:
    """devices: {"system": dev, "mic": dev}; each dev has .recorder(samplerate, channels, blocksize) whose .record(n)
    returns float32 frames (soundcard's interface; tests pass fakes)."""

    def __init__(self, devices: dict, folder: Path | None = None, on_audio=None):
        if not devices:
            raise RuntimeError("Mikrofon ya da hoparlör bulunamadı")
        stamp = datetime.now().strftime("%Y-%m-%d %H.%M.%S")
        self.folder = folder or recordings_dir() / stamp
        self.folder.mkdir(parents=True, exist_ok=True)
        self.devices = devices
        self.on_audio = on_audio          # live text: called with (source, 16 kHz samples)
        self.started = time.time()
        self.samples = {k: 0 for k in devices}
        self.levels = {k: 0.0 for k in devices}
        self.errors: dict[str, str] = {}
        self.paused = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._meta({"state": "recording", "started": self.started, "sources": list(devices),
                    "title": self.title()})
        _active.add(self.folder.name)

    def title(self) -> str:
        return "Toplantı " + datetime.fromtimestamp(self.started).strftime("%Y-%m-%d %H.%M")

    def _meta(self, m: dict) -> None:
        p = self.folder / "meta.json"
        try:
            old = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            old = {}
        p.write_text(json.dumps({**old, **m}, ensure_ascii=False), "utf-8")

    def start(self) -> "MeetingRecorder":
        for name, dev in self.devices.items():
            t = threading.Thread(target=self._capture, args=(name, dev), daemon=True, name=f"rec-{name}")
            t.start()
            self._threads.append(t)
        return self

    def _capture(self, name: str, dev) -> None:
        ds = Downsampler()
        path = self.folder / f"{name}.pcm"
        try:
            with open(path, "ab") as f, dev.recorder(samplerate=CAP_SR, channels=2 if name == "system" else 1,
                                                     blocksize=1024) as r:
                while not self._stop.is_set():
                    block = r.record(numframes=BLOCK)
                    y = ds(block)
                    self.levels[name] = float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) if len(y) else 0.0
                    if self.paused:
                        continue  # keep reading so the device buffer does not overflow, but keep nothing
                    f.write(to_int16(y))
                    f.flush()
                    self.samples[name] += len(y)
                    if self.on_audio:
                        try:
                            self.on_audio(name, y)
                        except Exception:
                            pass
        except Exception as e:  # device unplugged, access denied …: the other source keeps going
            self.errors[name] = str(e)[:200]
            self.levels[name] = 0.0

    def seconds(self) -> float:
        return max(self.samples.values(), default=0) / SR

    def status(self) -> dict:
        return {"active": not self._stop.is_set(), "paused": self.paused, "seconds": round(self.seconds(), 1),
                "levels": {k: round(v, 4) for k, v in self.levels.items()}, "sources": list(self.devices),
                "errors": dict(self.errors), "title": self.title(), "folder": str(self.folder)}

    def pause(self, on: bool = True) -> None:
        self.paused = bool(on)

    def _join(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)
        _active.discard(self.folder.name)

    def stop(self) -> Path:
        """Stop and mix: returns the WAV to process."""
        self._join()
        self._meta({"state": "stopped", "stopped": time.time()})
        return finish(self.folder)

    def cancel(self) -> None:
        self._join()
        shutil.rmtree(self.folder, ignore_errors=True)


def finish(folder: Path) -> Path:
    """Mix the raw tracks of a recording folder into <title>.wav (also used to recover after a crash)."""
    try:
        meta = json.loads((folder / "meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        meta = {}
    tracks = [read_pcm(folder / f"{s}.pcm") for s in SOURCES]
    audio = mix(tracks)
    if len(audio) < SR:  # under a second: nothing worth processing
        raise ValueError("Kayıt boş: en az bir saniye ses gerekiyor")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", meta.get("title") or folder.name).strip() or "Toplanti"
    out = folder / f"{name}.wav"
    write_wav(out, audio)
    meta["state"] = "mixed"
    meta["wav"] = out.name
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    for s in SOURCES:  # the WAV holds everything now
        (folder / f"{s}.pcm").unlink(missing_ok=True)
    return out


def leftovers() -> list[dict]:
    """Recordings cut off by a crash (still 'recording') or mixed but never processed."""
    out = []
    for d in sorted(recordings_dir().iterdir()) if recordings_dir().exists() else []:
        if not d.is_dir():
            continue
        try:
            meta = json.loads((d / "meta.json").read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if d.name in _active:
            continue
        if meta.get("state") in ("recording", "stopped"):
            secs = max((p.stat().st_size for p in d.glob("*.pcm")), default=0) / 2 / SR
        elif meta.get("state") == "mixed" and (d / str(meta.get("wav", ""))).is_file():
            secs = max(0, (d / meta["wav"]).stat().st_size - 44) / 2 / SR
        else:
            continue
        if secs >= 1:
            out.append({"folder": d.name, "title": meta.get("title") or d.name, "seconds": round(secs, 1)})
    return out


_active: set[str] = set()  # folders being recorded right now (never offered as leftovers)


def recover(name: str) -> Path:
    """The WAV of a leftover recording (mixing its raw tracks first when needed)."""
    folder = recordings_dir() / Path(name).name
    try:
        meta = json.loads((folder / "meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        raise ValueError("Bu kayıt bulunamadı") from None
    if meta.get("state") == "mixed" and (folder / str(meta.get("wav", ""))).is_file():
        return folder / meta["wav"]
    return finish(folder)


def discard(name: str) -> None:
    folder = recordings_dir() / Path(name).name
    if folder.parent == recordings_dir() and folder.name not in _active:
        shutil.rmtree(folder, ignore_errors=True)


def done(folder: Path) -> None:
    """The mixed WAV is in a job now: the raw tracks are not needed any more."""
    shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- live text (main edition)
class LiveWriter:
    """Writes the meeting as text while it is recorded, a few seconds behind.

    Every ~12 s of new audio is cut at the quietest moment near its end (not inside a word) and transcribed in a
    low-priority thread with the loaded speech model. When transcribing takes longer than the audio itself twice in a
    row the PC is too busy (slides, video call …): live text stops by itself and says so; the recording goes on and
    the full text is made after Stop.
    """

    def __init__(self, transcribe, every: float = 12.0, on_stop=None):
        self.transcribe = transcribe      # (samples, duration) -> text
        self.every = every
        self.on_stop = on_stop
        self.lines: list[dict] = []
        self.state = "running"            # running | stopped | slow | error
        self.error = ""
        self._buf = {s: [] for s in SOURCES}
        self._len = {s: 0 for s in SOURCES}
        self._sources: set[str] = set()
        self._offset = 0.0                # seconds already written
        self._slow = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="live-text")

    def start(self, sources) -> "LiveWriter":
        self._sources = set(sources)
        self._thread.start()
        return self

    def feed(self, source: str, samples: np.ndarray) -> None:
        if self.state != "running":
            return
        with self._lock:
            self._buf[source].append(samples)
            self._len[source] += len(samples)
        self._wake.set()

    def stop(self, state: str = "stopped") -> None:
        if self.state == "running":
            self.state = state
        self._wake.set()

    def status(self) -> dict:
        return {"state": self.state, "error": self.error, "lines": list(self.lines)}

    def _take(self, force: bool = False) -> np.ndarray | None:
        with self._lock:
            have = min(self._len[s] for s in self._sources) if self._sources else 0
            if have < self.every * SR and not (force and have > SR // 2):
                return None
            tracks = []
            for s in self._sources:
                a = np.concatenate(self._buf[s]) if self._buf[s] else np.zeros(0, np.float32)
                tracks.append(a)
            # look at most 1.25 x the chunk length ahead: when live text is behind, chunks stay ~equal in size
            limit = have if force else min(have, int(self.every * 1.25 * SR))
            mixed = mix([t[:limit] for t in tracks])
            cut = limit if force else quiet_cut(mixed)
            for s, a in zip(self._sources, tracks):
                rest = a[cut:]
                self._buf[s] = [rest] if len(rest) else []
                self._len[s] = len(rest)
            return mixed[:cut]

    def _run(self) -> None:
        _lower_priority()
        while self.state == "running":
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            chunk = self._take()
            if chunk is None:
                continue
            dur = len(chunk) / SR
            t0 = time.time()
            try:
                text = (self.transcribe(chunk, dur) or "").strip()
            except Exception as e:
                self.error = str(e)[:200]
                self.stop("error")
                break
            took = time.time() - t0
            if text:
                self.lines.append({"start": round(self._offset, 1), "end": round(self._offset + dur, 1), "text": text})
            self._offset += dur
            self._slow = self._slow + 1 if took > dur else 0
            if self._slow >= 2:
                self.stop("slow")
        if self.on_stop:
            try:
                self.on_stop(self.state)
            except Exception:
                pass


def quiet_cut(x: np.ndarray, win: int = SR // 10) -> int:
    """Index of the quietest 0.1 s in the last 40 % of x: a pause between words, so no word is cut in half."""
    n = len(x)
    lo = int(n * 0.6)
    if n - lo < win * 2:
        return n
    e = np.convolve(x[lo:].astype(np.float64) ** 2, np.ones(win), mode="valid")
    return lo + int(np.argmin(e)) + win // 2


def _lower_priority() -> None:
    """Live text must never make the PC (or the meeting app) stutter."""
    try:
        import ctypes

        k = ctypes.windll.kernel32
        k.SetThreadPriority(k.GetCurrentThread(), -1)  # THREAD_PRIORITY_BELOW_NORMAL
    except Exception:
        pass
