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
_stop: dict[str, str] = {}  # job id -> "pause" | "cancel", set by request_stop, cleared when the job ends
_current: dict[str, str | None] = {"id": None}  # the job that holds the queue lock
_order: list[str] = []  # waiting jobs, first in first out (the head goes next)
_order_lock = threading.Lock()
ASK_TIMEOUT = 120.0  # seconds a job waits for the user's noise-cleanup choice before the automatic decision is used
_answers: dict[str, dict] = {}  # job id -> the user's choice, put there by answer_noise
_asking: set[str] = set()  # jobs that are waiting for a choice right now


class JobStopped(Exception):
    """Raised inside a running job when the user paused or cancelled it."""


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


def request_stop(job_id: str, mode: str) -> None:
    """Ask a running or queued job to stop: mode "pause" keeps its finished parts, "cancel" deletes it."""
    if mode not in ("pause", "cancel"):
        raise ValueError("mode must be 'pause' or 'cancel'")
    if mode == "pause" and _stop.get(job_id) == "cancel":
        return  # cancel wins
    _stop[job_id] = mode


def answer_noise(job_id: str, use_cleaned: bool, dont_ask: bool = False) -> bool:
    """The user's answer to the noise-cleanup question of a waiting job. False when nothing is being asked."""
    if job_id not in _asking:
        return False
    _answers[job_id] = {"cleaned": bool(use_cleaned), "dont_ask": bool(dont_ask)}
    return True


def _check_stop(job_id: str) -> None:
    if job_id in _stop:
        raise JobStopped(_stop[job_id])


def _wait_for_turn(job_id: str) -> None:
    """Wait until this job is first in line and the queue lock is free. A queued job stays stoppable:
    a paused or cancelled one raises JobStopped and just leaves the line."""
    while True:
        _check_stop(job_id)
        with _order_lock:
            is_head = not _order or _order[0] == job_id or job_id not in _order
        if is_head and _queue_lock.acquire(timeout=0.2):
            break
        if not is_head:
            time.sleep(0.2)
    try:
        _check_stop(job_id)
    except BaseException:
        _queue_lock.release()
        raise


def run_job(job_id: str, src: Path | None, keep_source: bool = True, resume: bool = False) -> None:
    """keep_source=True: src is the user's own file and must never be deleted."""
    t_start = time.time()
    enqueue(job_id)  # no-op when the caller already did (start_job / resume_job do, to keep the order)
    held = False
    try:
        _wait_for_turn(job_id)
        held = True
        with _order_lock:  # now running: no longer "waiting"
            _current["id"] = job_id
            if job_id in _order:
                _order.remove(job_id)
        _run(job_id, src, resume, t_start)
        _stop.pop(job_id, None)
    except JobStopped:
        mode = _stop.pop(job_id, "pause")  # flag cleared first: a resume right after must not see it
        if mode == "cancel":
            store.delete_job(job_id)
        else:
            try:
                store.update_job(job_id, status="paused")  # stage and progress stay as they were
            except (OSError, ValueError):
                pass
    except Exception as e:
        if _stop.pop(job_id, None) == "cancel":  # cancelled while failing: no error to show
            store.delete_job(job_id)
        else:
            _fail(job_id, e)
    finally:
        _leave_line(job_id)
        if held:
            _current["id"] = None
            _queue_lock.release()
        if src is not None and not keep_source:  # only temporary copies are removed
            try:
                Path(src).unlink(missing_ok=True)
            except OSError:
                pass


def _fail(job_id: str, e: Exception) -> None:
    if isinstance(e, ValueError):  # user-facing problems (bad file etc.)
        store.update_job(job_id, status="error", stage="error", error=str(e))
    else:
        traceback.print_exc()
        store.update_job(job_id, status="error", stage="error", error=f"{type(e).__name__}: {e}")


def _run(job_id: str, src: Path | None, resume: bool, t_start: float) -> None:
    from . import asr, audio, chunking, diarize

    jp = store.job_path(job_id)
    job = store.read_transcript(job_id)
    status = {"stage": "converting", "progress": 0.0, "dprogress": 0.0}

    def push(**extra):
        store.update_job(job_id, status="running", stage=status["stage"],
                         progress=round(status["progress"], 3), dprogress=round(status["dprogress"], 3), **extra)

    push()
    if resume and (jp / "audio.mp3").exists():
        samples, duration = audio.decode(jp / "audio.mp3")
    else:
        samples, duration = audio.convert(src, jp / "audio.mp3")
    t_decoded = time.time()
    _check_stop(job_id)

    parts = job.get("parts") if resume and job.get("parts") else chunking.split(samples)
    asr_samples = _clean_noise(job_id, jp, job, samples, parts, resume, status, push)
    status["stage"] = "loading_model"
    push(duration=duration, parts=parts)
    asr.load_model()
    device = asr.status()["device_in_use"]

    # Speakers are found on the whole recording (so a voice keeps one label across parts).
    # With a GPU doing the transcription, the CPU is free: run both at the same time.
    diar: dict = {}
    cancel = threading.Event()  # stops speaker separation if transcription fails
    last_d = [0.0]

    def dprog(p):
        if job_id in _stop:
            cancel.set()
            raise JobStopped(_stop[job_id])
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
    th = threading.Thread(target=run_diar, daemon=True) if parallel else None
    if th:
        th.start()
    try:
        return _transcribe_and_finish(job_id, jp, job, samples, duration, parts, device, parallel,
                                      th, diar, run_diar, dprog, push, status, resume, t_start, t_decoded, asr_samples)
    finally:
        cancel.set()  # no-op when finished; stops a still running separation after an error or a stop


def _clean_noise(job_id, jp, job, samples, parts, resume, status, push):
    """Noise cleanup for the transcription (Settings: Off / Auto / Always). Returns the samples the speech
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
                    clean, note = _ask_user(job_id, jp, samples, snr, thr, clean, status, push)
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
        status["stage"] = "cleaning"
        push()
        t0 = time.time()
        last = [0.0]

        def prog(p):
            _check_stop(job_id)
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


def _ask_user(job_id, jp, samples, snr, thr, auto_clean, status, push):
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
            _check_stop(job_id)  # pause / cancel while waiting
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
                           th, diar, run_diar, dprog, push, status, resume, t_start, t_decoded, asr_samples=None):
    from . import asr, diarize

    if asr_samples is None:  # speech model hears the recording itself unless a cleaned copy is passed
        asr_samples = samples

    status["stage"] = "transcribing"
    push(device=device)
    part_dir = jp / "parts"
    part_dir.mkdir(exist_ok=True)
    words: list[Word] = []
    langs: Counter = Counter()
    last_t = [0.0]
    t_asr = time.time()
    if not (resume and (part_dir / "0.json").exists()) or True:
        asr.detect_languages(asr_samples)  # which language(s) the whole recording is in (one cheap pass)
    for i, (a, b) in enumerate(parts):
        _check_stop(job_id)  # between parts
        f = part_dir / f"{i}.json"
        if resume and f.exists():  # already done before the app was closed
            saved = json.loads(f.read_text("utf-8"))
        else:
            def tprog(p, a=a, b=b):
                _check_stop(job_id)  # the engine stops (whisper.cpp: process killed) when this raises
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
    try:  # the user's glossary: names and terms the model spells wrong
        from . import glossary

        words, gloss_changes = glossary.apply(words)
    except Exception:
        traceback.print_exc()
        gloss_changes = []
    language = langs.most_common(1)[0][0] if langs else None

    status["stage"] = "diarizing"
    push(language=language)
    if th:
        th.join()
    else:
        run_diar()
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
    speakers = {str(i): f"Speaker {i + 1}" for i in range(n)}
    from . import names
    from .names import detect_names

    for k, name in detect_names(segments, speakers).items():
        speakers[str(k)] = name
    from . import people  # ---- people: saved voices override the guesses (free when nobody is saved)

    voices = people.apply_to_job(samples, segments, speakers)
    # people are learned only after the recording is saved (the audio file is needed): remember who introduced themselves
    intros = names.detect_intros(segments) if asr.get_settings().get("learn_people", True) else {}
    timings = {"audio": round(duration, 1), "device": device, "parallel": parallel,
               "decode": round(t_decoded - t_start, 1), "asr": round(asr_secs, 1),
               "diar": round(diar["secs"] + (time.time() - t_ref), 1), "total": round(time.time() - t_start, 1)}
    from . import benchmarks

    benchmarks.record(timings, resumed=resume)  # feeds the ETA estimates
    store.update_job(
        job_id, status="done", stage="done", progress=1.0, dprogress=1.0, segments=segments,
        mixed=asr.language_mode() == "mixed", glossary_changes=gloss_changes,
        speakers=speakers, timings=timings, **voices,
        # frozen copy of the model output for the "Original" export
        original_segments=[{k: s[k] for k in ("start", "end", "speaker", "text_original")} for s in segments],
    )
    if intros:  # learn the voices of the people who introduced themselves (never fails the recording)
        try:
            mine = {k: v for k, v in intros.items() if speakers.get(str(k)) == v}
            if mine:
                store.update_job(job_id, learned=people.learn_from_job(job_id, mine))
        except Exception:
            traceback.print_exc()
    try:  # meeting mode: analyse right away; this must never fail a transcription
        if asr.get_settings().get("meeting_mode"):
            from . import analysis

            analysis.start(job_id)
    except Exception:
        traceback.print_exc()
