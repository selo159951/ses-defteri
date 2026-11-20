"""decode -> split into parts -> transcribe parts (+ speakers in parallel) -> merge.

Progress is written to the job file. Every finished part is saved to
jobs/<id>/parts/<n>.json, so a job interrupted by closing the app resumes where
it stopped (run_job(..., resume=True)).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections import Counter
from pathlib import Path

from . import store
from .merge import Word, assign_speakers, build_segments

SR = 16000
_queue_lock = threading.Lock()  # one heavy job at a time

# ---- pause / cancel ----
_stop: dict[str, str] = {}              # job id -> "pause" | "cancel" (asked for, not done yet)
_active: set[str] = set()               # jobs that have a run_job thread (queued or running)
_cancel_events: dict[str, threading.Event] = {}  # lets request_stop stop the speaker separation at once
_current: dict[str, str | None] = {"id": None}   # the job that holds the queue lock
_order: list[str] = []                  # waiting jobs, first in first out (the head goes next)
_order_lock = threading.Lock()
ASK_TIMEOUT = 120.0  # seconds a job waits for the user's noise-cleanup choice before the automatic decision is used
_answers: dict[str, dict] = {}  # job id -> the user's choice, put there by answer_noise
_asking: set[str] = set()  # jobs that are waiting for a choice right now


class JobStopped(Exception):
    """Raised inside a job when the user asked to pause or cancel it."""

    def __init__(self, mode: str):
        super().__init__(mode)
        self.mode = mode


def enqueue(job_id: str) -> None:
    """Take a place at the end of the line. Called in submission order (before the job's thread is
    started), which is what makes the processing order first-in-first-out."""
    with _order_lock:
        if job_id not in _order:
            _order.append(job_id)


def _leave_line(job_id: str) -> None:
    with _order_lock:
        if job_id in _order:
            _order.remove(job_id)


def queue_ids() -> list[str]:
    """Jobs that are waiting for their turn, in the order they will run (the running one is not in it)."""
    with _order_lock:
        return list(_order)


def is_active(job_id: str) -> bool:
    return job_id in _active


def request_stop(job_id: str, mode: str) -> bool:
    """mode: "pause" (keep the finished parts, can be resumed) or "cancel" (remove the job).
    Returns False when the job is not being processed at the moment."""
    if mode not in ("pause", "cancel"):
        raise ValueError("mode must be pause or cancel")
    if job_id not in _active:
        return False
    _stop[job_id] = mode
    ev = _cancel_events.get(job_id)
    if ev:
        ev.set()
    return True


def answer_noise(job_id: str, use_cleaned: bool, dont_ask: bool = False) -> bool:
    """The user's answer to the noise-cleanup question of a waiting job. False when nothing is being asked."""
    if job_id not in _asking:
        return False
    _answers[job_id] = {"cleaned": bool(use_cleaned), "dont_ask": bool(dont_ask)}
    return True


def _check(job_id: str) -> None:
    mode = _stop.get(job_id)
    if mode:
        raise JobStopped(mode)


def _heartbeat(job_id: str, done: threading.Event) -> None:
    """The page shows "working" from this: it changes every 2 s while the job really runs."""
    while not done.wait(2.0):
        try:
            store.update_job(job_id, heartbeat=round(time.time(), 1))
        except Exception:  # job removed meanwhile
            return


def _wait_for_turn(job_id: str) -> None:
    """Wait until this job is first in line and the queue lock is free; say which recording is in front,
    and stay stoppable (a paused or cancelled queued job just leaves the line)."""
    announced = None
    while True:
        _check(job_id)
        with _order_lock:
            ahead = _order.index(job_id) if job_id in _order else 0
            front = _order[ahead - 1] if ahead > 0 else None
            is_head = ahead == 0
        if is_head and _queue_lock.acquire(timeout=0.2):
            break
        if not is_head:
            time.sleep(0.2)
        other = front or _current["id"]
        if other and other != announced:
            announced = other
            try:
                name = store.read_transcript(other)["filename"]
            except Exception:
                name = ""
            _safe_update(job_id, waiting_for=name or "?")
    try:
        _check(job_id)
    except BaseException:
        _queue_lock.release()
        raise


def run_job(job_id: str, src: Path | None, keep_source: bool = True, resume: bool = False) -> None:
    """keep_source=True: src is the user's own file and must never be deleted."""
    t_start = time.time()
    _active.add(job_id)
    enqueue(job_id)  # no-op when the caller already did (start_job / resume_job do, to keep the order)
    hb_done = threading.Event()
    held = False
    try:
        _wait_for_turn(job_id)
        held = True
        with _order_lock:  # now running: no longer "waiting"
            _current["id"] = job_id
            if job_id in _order:
                _order.remove(job_id)
        threading.Thread(target=_heartbeat, args=(job_id, hb_done), daemon=True).start()
        _run(job_id, src, resume, t_start)
    except JobStopped as e:
        _finish_stop(job_id, e.mode)
    except ValueError as e:  # user-facing problems (bad file etc.)
        _safe_update(job_id, status="error", stage="error", error=str(e), waiting_for=None)
    except Exception as e:  # surfaced in UI
        if job_id in _stop:  # e.g. the separation was cancelled because of the stop request
            _finish_stop(job_id, _stop[job_id])
            return
        traceback.print_exc()
        _safe_update(job_id, status="error", stage="error", error=f"{type(e).__name__}: {e}", waiting_for=None)
    finally:
        hb_done.set()
        _leave_line(job_id)
        if held:
            _current["id"] = None
            _queue_lock.release()
        _stop.pop(job_id, None)
        _cancel_events.pop(job_id, None)
        _active.discard(job_id)
        if src is not None and not keep_source:  # only temporary copies are removed
            try:
                Path(src).unlink(missing_ok=True)
            except OSError:
                pass


def _safe_update(job_id: str, **fields) -> None:
    try:
        store.update_job(job_id, **fields)
    except (OSError, ValueError):  # job folder is gone
        pass


def _finish_stop(job_id: str, mode: str) -> None:
    if mode == "cancel":
        try:
            store.delete_job(job_id)
        except (OSError, ValueError):
            pass
        return
    jp = store.job_path(job_id)
    try:
        if not store.read_transcript(job_id).get("audio_ready"):
            (jp / "audio.mp3").unlink(missing_ok=True)  # half written, redone on resume
        store.update_job(job_id, status="paused", stage="paused", waiting_for=None)
    except (OSError, ValueError):
        pass


def _run(job_id: str, src: Path | None, resume: bool, t_start: float) -> None:
    jp = store.job_path(job_id)
    job = store.read_transcript(job_id)
    status = {"stage": "converting", "progress": 0.0, "dprogress": 0.0, "cprogress": 0.0}

    def push(**extra):
        store.update_job(job_id, status="running", stage=status["stage"], progress=round(status["progress"], 3),
                         dprogress=round(status["dprogress"], 3), cprogress=round(status["cprogress"], 3),
                         heartbeat=round(time.time(), 1), **extra)

    def enter(stage: str, **extra):
        status["stage"] = stage
        push(stage_started=round(time.time(), 1), **extra)

    # Show "converting" at once: the imports below (speech and speaker libraries) take many seconds
    # on a cold start, and until now the job still said "queued" during all of that.
    ready = bool(job.get("audio_ready", True)) if resume else False  # older jobs have no flag: their mp3 is whole
    store.update_job(job_id, waiting_for=None, run_started=round(t_start, 1), audio_ready=ready)
    enter("converting")
    from . import asr, audio, chunking, diarize, hardware

    _check(job_id)
    if ready and (jp / "audio.mp3").exists():
        samples, duration = audio.decode(jp / "audio.mp3")
    else:
        src = src or (Path(job["source_path"]) if job.get("source_path") else None)
        if src is None or not Path(src).is_file():
            raise ValueError("Özgün dosya bulunamadı, dosyayı yeniden ekle")

        def cprog(p):
            status["cprogress"] = p
            push()
            _check(job_id)

        samples, duration = audio.convert(src, jp / "audio.mp3", cprog)
        store.update_job(job_id, audio_ready=True)
    status["cprogress"] = 1.0
    t_decoded = time.time()
    _check(job_id)

    parts = job.get("parts") if resume and job.get("parts") else chunking.split(samples)
    asr_samples = _clean_noise(job_id, jp, job, samples, parts, resume, status, push, enter)
    enter("loading_model", duration=duration, parts=parts)
    try:
        asr.load_model(note=lambda n: push(stage_note=n))  # first use: a short speed test (job field stage_note)
    finally:
        push(stage_note=None)
    device = asr.status()["device_in_use"]
    _check(job_id)

    # Speakers are found on the whole recording (so a voice keeps one label across parts).
    # With a GPU doing the transcription, the CPU is free: run both at the same time.
    diar: dict = {}
    cancel = threading.Event()  # stops speaker separation if transcription fails or the user stops
    _cancel_events[job_id] = cancel
    last_d = [0.0]

    def dprog(p):
        _check(job_id)
        status["dprogress"] = p
        if p - last_d[0] >= 0.02:
            last_d[0] = p
            push()

    def run_diar():
        t0 = time.time()
        try:
            diar["turns"] = diarize.diarize(samples, lambda p: dprog(p * 0.85), cancel)
        except Exception as e:  # re-raised in the main thread
            diar["error"] = e
        diar["secs"] = time.time() - t0

    parallel = device != "cpu" and _parallel_enabled()
    diarize.set_threads(hardware.diarize_threads(parallel=parallel))  # all cores alone, two fewer next to a GPU run
    th = threading.Thread(target=run_diar, daemon=True) if parallel else None
    if th:
        th.start()
    try:
        return _transcribe_and_finish(job_id, jp, job, samples, duration, parts, device, parallel,
                                      th, diar, run_diar, dprog, push, enter, status, resume, t_start, t_decoded, asr_samples)
    finally:
        cancel.set()  # no-op when finished; stops a still running separation after an error
        if th:
            th.join(timeout=15)


def _clean_noise(job_id, jp, job, samples, parts, resume, status, push, enter):
    """Noise cleanup for the transcription (Options: Automatic / Always / Off). Returns the samples the speech
    model should hear: a cleaned copy of the recording, or `samples` itself when nothing is done.
    The playback mp3 is written before this and always keeps the original. Never fails a job."""
    from . import asr, denoise

    mode = denoise.normalize_mode(asr.get_settings().get("denoise", denoise.DEFAULT_MODE))
    try:
        if "noise_ask" in job:  # a question left over from a run that was closed while waiting
            store.update_job(job_id, noise_ask=None)
        all_done = bool(resume and parts and all((jp / "parts" / f"{i}.json").exists() for i in range(len(parts))))
        note = None
        if resume and "noise" in job:  # same decision as the first run
            clean, snr = bool(job["noise"].get("cleaned")), job["noise"].get("snr")
        else:
            thr = denoise.current_threshold()
            clean, snr = denoise.should_denoise(mode, samples, thr)
            clean = clean and denoise.available()
            if mode == "auto" and not all_done and denoise.available():
                ans = denoise.answers()
                if denoise.should_ask(snr, ans, thr, asr.get_settings().get("denoise_ask", True) is not False):
                    clean, note = _ask_user(job_id, jp, samples, snr, thr, clean, status, push, enter)
        if all_done:
            clean = False  # every part is already transcribed: nothing left to hear
        if snr is not None and snr == snr:  # not NaN (Off mode does not measure)
            snr = round(float(snr), 1)
        else:
            snr = None
        info = {"mode": mode, "snr": snr, "cleaned": clean}
        if note:
            info["choice"] = note  # "user" or "timeout" (the automatic decision was used)
        store.update_job(job_id, noise=info)
        if not clean:
            return samples
        enter("cleaning")
        t0 = time.time()
        last = [0.0]

        def prog(p):
            _check(job_id)
            if p - last[0] >= 0.05:
                last[0] = p
                push(clean_progress=round(p, 2))

        out = denoise.denoise(samples, prog)
        store.update_job(job_id, noise={**info, "cleaned": True, "secs": round(time.time() - t0, 1)})
        return out
    except JobStopped:
        raise
    except Exception:  # a broken cleaner must never lose the recording: use the original audio
        traceback.print_exc()
        return samples


def _ask_user(job_id, jp, samples, snr, thr, auto_clean, status, push, enter):
    """Noisy-looking recording: cut a short speech excerpt, clean only that, and let the user hear both before the
    whole recording is processed. Waits for the answer (pause and cancel still work); after ASK_TIMEOUT seconds the
    automatic decision `auto_clean` is used so the line never stalls. Returns (clean?, "user" | "timeout").
    If the excerpt cannot be made the automatic decision is returned without asking."""
    from . import asr, denoise

    files = [jp / "ab_original.wav", jp / "ab_cleaned.wav"]
    try:
        orig, clean = denoise.make_excerpt(samples)
        denoise.write_wav(files[0], orig)
        denoise.write_wav(files[1], clean)
    except Exception:
        traceback.print_exc()
        return auto_clean, None
    status["stage"] = "awaiting_choice"
    _answers.pop(job_id, None)
    _asking.add(job_id)
    deadline = time.time() + ASK_TIMEOUT
    try:
        push(noise_ask={"snr": round(float(snr), 1), "threshold": round(float(thr), 1), "auto": bool(auto_clean),
                        "original": files[0].name, "cleaned": files[1].name, "deadline": deadline})
        ans = None
        while ans is None and time.time() < deadline:
            _check(job_id)  # pause / cancel while waiting
            ans = _answers.pop(job_id, None)
            if ans is None:
                time.sleep(0.05)
    finally:
        _asking.discard(job_id)
        _answers.pop(job_id, None)
        for f in files:
            f.unlink(missing_ok=True)
        try:
            store.update_job(job_id, noise_ask=None)
        except (OSError, ValueError):
            pass
    status["stage"] = "converting"
    if ans is None:
        return auto_clean, "timeout"
    denoise.record_choice(snr, ans["cleaned"])
    if ans["dont_ask"]:
        asr.set_setting("denoise_ask", False)
    return ans["cleaned"], "user"


def _parallel_enabled() -> bool:
    import os

    return (os.environ.get("SESDEFTERI_SEQUENTIAL") or os.environ.get("MEETTRANSCRIBER_SEQUENTIAL")) != "1"


def _transcribe_and_finish(job_id, jp, job, samples, duration, parts, device, parallel,
                           th, diar, run_diar, dprog, push, enter, status, resume, t_start, t_decoded, asr_samples=None):
    from . import asr, diarize, hardware

    if asr_samples is None:  # the speech model hears the recording itself unless a cleaned copy is passed
        asr_samples = samples

    enter("transcribing", device=device)
    part_dir = jp / "parts"
    part_dir.mkdir(exist_ok=True)
    words: list[Word] = []
    langs: Counter = Counter()
    last_t = [0.0]
    t_asr = time.time()
    if not (resume and (part_dir / "0.json").exists()) or True:
        asr.detect_languages(asr_samples)  # which language(s) the whole recording is in (one cheap pass)
    for i, (a, b) in enumerate(parts):
        _check(job_id)
        push(part=i + 1)
        f = part_dir / f"{i}.json"
        if resume and f.exists():  # already done before the app was closed
            saved = json.loads(f.read_text("utf-8"))
        else:
            def tprog(p, a=a, b=b):
                _check(job_id)
                status["progress"] = (a + p * (b - a)) / duration
                if status["progress"] - last_t[0] >= 0.01:
                    last_t[0] = status["progress"]
                    push(part=i + 1)

            ws, lang = asr.transcribe(asr_samples[int(a * SR):int(b * SR)], b - a, tprog)
            saved = {"lang": lang, "words": [[round(w.start + a, 3), round(w.end + a, 3), w.text, round(w.prob, 3)] for w in ws]}
            f.write_text(json.dumps(saved, ensure_ascii=False), "utf-8")
        words += [Word(w[0], w[1], w[2], w[3] if len(w) > 3 else 1.0) for w in saved["words"]]
        langs[saved["lang"]] += b - a
        status["progress"] = b / duration
        push(part=i + 1)
    asr_secs = time.time() - t_asr
    language = langs.most_common(1)[0][0] if langs else None

    _check(job_id)
    enter("diarizing", language=language)
    if th:
        th.join()
    else:
        run_diar()
    diarize.set_threads(hardware.diarize_threads())  # the refinement below runs alone
    if "error" in diar:
        raise diar["error"]
    turns = diar["turns"]
    t_ref = time.time()
    spk = assign_speakers(words, turns)
    margins: list[float] = []
    spk = diarize.refine_by_sentence(samples, words, spk, lambda p: dprog(0.85 + p * 0.15), margins)
    spk = diarize.merge_split_speakers(samples, words, spk)  # one person heard as two speakers
    segments = build_segments(words, turns, speakers=spk, margins=margins or None)

    n = len({s["speaker"] for s in segments}) or 1
    speakers = {str(i): f"Speaker {i + 1}" for i in range(n)}  # simple app: no name finding, no saved voices
    timings = {"audio": round(duration, 1), "device": device, "parallel": parallel,
               "decode": round(t_decoded - t_start, 1), "asr": round(asr_secs, 1),
               "diar": round(diar["secs"] + (time.time() - t_ref), 1), "total": round(time.time() - t_start, 1)}
    from . import benchmarks

    benchmarks.record(timings, resumed=resume)  # feeds the remaining-time estimates
    store.update_job(
        job_id, status="done", stage="done", progress=1.0, dprogress=1.0, segments=segments,
        mixed=False, waiting_for=None, glossary_changes=[], speakers=speakers, timings=timings,
        # frozen copy of the model output for the "Original" export
        original_segments=[{k: s[k] for k in ("start", "end", "speaker", "text_original")} for s in segments],
    )
