"""Everything the window can ask the backend for (window.pywebview.api.<method>).

There is no HTTP server: the page calls these methods directly through pywebview's
JS<->Python bridge, and files are read from disk by path. Every method returns plain
JSON-able data; raising an exception rejects the JS promise with its message.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from . import asr, denoise, export, models, store, updater, version
from . import pipeline
from .watcher import Watcher
from .pipeline import run_job
from .llm_api import LlmApi
from .system_api import SystemApi

EXPORT_TYPES = {
    "docx": "Word document (*.docx)",
    "txt": "Text file (*.txt)",
    "md": "Markdown (*.md)",
    "srt": "Subtitles (*.srt)",
    "json": "JSON (*.json)",
}
MEDIA_EXT = "*.mp3;*.wav;*.m4a;*.mp4;*.ogg;*.opus;*.flac;*.aac;*.webm;*.mkv;*.mov;*.wma;*.amr;*.3gp"
MEDIA_SUFFIXES = {"." + e.split(".")[-1] for e in MEDIA_EXT.split(";")}
MEDIA_TYPES = (f"Audio and video ({MEDIA_EXT})", "All files (*.*)")


def _safe_name(s: str, limit: int = 80) -> str:
    """Text that is safe inside a Windows file name."""
    s = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in s).strip(" .")
    return (s[:limit].strip(" .")) or "kayit"


def _first(result) -> str | None:
    if not result:
        return None
    return result if isinstance(result, str) else result[0]


def _write(path: Path, data: str | bytes) -> None:
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _job(job_id: str) -> dict:
    try:
        return store.read_transcript(job_id)
    except (FileNotFoundError, ValueError):
        raise ValueError("job not found") from None


class Api(SystemApi, LlmApi):
    """Methods starting with "_" are not exposed to the page."""

    def __init__(self, window_getter=None):
        self._get_window = window_getter
        self._watcher = Watcher(self.start_jobs)
        if self._watcher.config()["enabled"]:
            self._watcher.start()

    def _window(self):
        if self._get_window:
            return self._get_window()
        import webview

        return webview.windows[0]

    # ---------------- recordings ----------------
    def list_jobs(self, q: str = "") -> list[dict]:
        return store.list_jobs(q or "")

    def get_job(self, job_id: str) -> dict:
        return _job(job_id)

    def delete_job(self, job_id: str) -> dict:
        _job(job_id)
        store.delete_job(job_id)
        return {"ok": True}

    def rename_job(self, job_id: str, name: str) -> dict:
        _job(job_id)
        return store.rename_job(job_id, name)

    def start_job(self, path: str) -> dict:
        """Start transcribing a file that is on disk (drag & drop or file picker).
        The job takes the next place in the line: files are processed one at a time, first come first served."""
        if models.first_run_blocking():
            raise ValueError("Ses tanıma modeli henüz indiriliyor. İndirme bitince kayıt ekleyebilirsin.")
        src = Path(path)
        if src.is_dir():
            raise ValueError(f"\"{src.name}\" bir klasör, ses ya da video dosyası değil. Klasörün içindeki dosyaları tek tek seç.")
        if not src.is_file():
            raise ValueError(f"\"{src.name}\" dosyası bulunamadı.")
        if src.suffix.lower() not in MEDIA_SUFFIXES:
            raise ValueError(f"\"{src.name}\" bir ses ya da video dosyası değil, atlandı.")
        job_id = store.create_job(src.name)  # a new folder per job: the same file twice gives two separate jobs
        store.update_job(job_id, source_path=str(src))  # lets a paused job start over if it stopped while converting
        pipeline.enqueue(job_id)  # here, not in the thread: the thread start order is not reliable
        threading.Thread(target=run_job, args=(job_id, src), kwargs={"keep_source": True},
                         daemon=True).start()
        return {"id": job_id, "filename": src.name}

    def start_jobs(self, paths: list) -> list:
        """Start several files in the given order. A file that cannot be used does not stop the others:
        it comes back as {"skipped": True, "filename", "error"}."""
        out = []
        for p in paths or []:
            try:
                out.append(self.start_job(str(p)))
            except Exception as e:
                out.append({"skipped": True, "filename": Path(str(p)).name, "error": str(e)})
        return out

    # ---------------- first start: the speech model is downloaded automatically ----------------
    def first_run_status(self) -> dict:
        """{needed, state (idle|downloading|done|error|no_internet), done, total, items[{label, done, total}],
        speed (bytes/s), eta (seconds|None), retrying, error (Turkish text|None)}"""
        return models.first_run_status()

    def start_first_run_download(self) -> dict:
        """Start (or retry) the download of the missing models; returns the same as first_run_status()."""
        return models.start_first_run_download()

    # ---------------- first start: two bundled sample recordings ----------------
    SAMPLES = (("ornek-uc-kisi.wav", "Örnek: üç kişilik toplantı"), ("ornek-tek-kisi.wav", "Örnek: tek kişi konuşuyor"))

    @staticmethod
    def _samples_dir() -> Path:
        import sys

        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS", "")) / "assets" / "samples"
        return Path(__file__).resolve().parents[1] / "assets" / "samples"

    def start_samples_once(self) -> list:
        """On the very first start (after the model download) process the two bundled sample recordings,
        so the user sees at once that the app works and what a result looks like. Only once per data folder."""
        if asr.get_settings().get("samples_started"):
            return []
        asr.set_setting("samples_started", True)
        out = []
        for fname, title in self.SAMPLES:
            p = self._samples_dir() / fname
            if not p.is_file():
                continue
            res = self.start_jobs([str(p)])
            for r in res:
                if r.get("id"):
                    try:
                        store.rename_job(r["id"], title)
                        r["filename"] = title
                    except Exception:
                        pass
            out += res
        return out

    def get_queue(self) -> dict:
        """The recording that is processed now and the ones waiting, in the order they will run."""
        def entry(i):
            try:
                return {"id": i, "filename": store.read_transcript(i)["filename"]}
            except (OSError, ValueError):
                return None  # removed meanwhile

        cur = pipeline._current["id"]
        running = entry(cur) if cur else None
        ask = None
        if running:  # the running recording waits for the noise-cleanup choice
            try:
                ask = store.read_transcript(cur).get("noise_ask")
            except (OSError, ValueError):
                ask = None
        return {"running": running, "ask": {"id": cur, "filename": running["filename"], **ask} if ask and running else None,
                "queued": [e for e in map(entry, pipeline.queue_ids()) if e]}

    def answer_noise(self, job_id: str, use_cleaned: bool, dont_ask: bool = False) -> dict:
        """The popup's answer: use the cleaned or the original audio for this recording."""
        return {"ok": pipeline.answer_noise(job_id, bool(use_cleaned), bool(dont_ask))}

    def reset_denoise_threshold(self) -> dict:
        denoise.reset_learning()
        return self.get_settings()

    def resume_job(self, job_id: str) -> dict:
        """Continue a job that was paused or interrupted (app closed while it was running)."""
        job = _job(job_id)
        if job["status"] not in ("interrupted", "error", "paused"):
            raise ValueError("this recording is not paused")
        if pipeline.is_active(job_id):
            raise ValueError("this recording is still being processed")
        has_audio = job.get("audio_ready", True) and (store.job_path(job_id) / "audio.mp3").exists()
        source = job.get("source_path")
        if not has_audio and not (source and Path(source).is_file()):
            raise ValueError("the audio of this recording is missing - add the file again")
        pipeline._stop.pop(job_id, None)
        store.update_job(job_id, status="queued", stage="queued", error=None, waiting_for=None)
        pipeline.enqueue(job_id)  # a resumed recording goes to the end of the line
        threading.Thread(target=run_job, args=(job_id, None), kwargs={"resume": True}, daemon=True).start()
        return {"id": job_id, "filename": job["filename"]}

    def pause_job(self, job_id: str) -> dict:
        """Stop after the current step; finished parts are kept and "resume_job" continues."""
        _job(job_id)
        if not pipeline.request_stop(job_id, "pause"):
            raise ValueError("this recording is not being processed")
        return {"ok": True}

    def cancel_job(self, job_id: str) -> dict:
        """Stop and remove a recording that is queued, running or paused."""
        job = _job(job_id)
        if pipeline.request_stop(job_id, "cancel"):
            return {"ok": True, "pending": True}
        if job["status"] == "done":
            raise ValueError("this recording is finished - delete it instead")
        store.delete_job(job_id)
        return {"ok": True}

    def pick_and_start(self) -> list:
        """Native "Open" dialog (several files allowed), then start them all in the chosen order.
        Returns a list (empty when the dialog was cancelled)."""
        import webview

        res = self._window().create_file_dialog(
            webview.FileDialog.OPEN, directory=self._last_dir("open_dir"), allow_multiple=True, file_types=MEDIA_TYPES)
        paths = [res] if isinstance(res, str) else list(res or [])
        if not paths:
            return []
        self._remember_dir("open_dir", str(Path(paths[0]).parent))
        return self.start_jobs(paths)

    # ---------------- editing ----------------
    def save_edits(self, job_id: str, texts: dict | None = None, segment_speakers: dict | None = None) -> dict:
        _job(job_id)
        store.save_edits(job_id, {int(k): v for k, v in (texts or {}).items()}, None,
                         {int(k): int(v) for k, v in (segment_speakers or {}).items()})
        return {"ok": True}

    def replace_transcript(self, job_id: str, segments: list, speakers: dict) -> dict:
        _job(job_id)
        return store.replace_transcript(job_id, segments, speakers)

    def split(self, job_id: str, segment_id: int, start: int, end: int, speaker: int) -> dict:
        _job(job_id)
        if not 0 <= int(speaker) < 20:
            raise ValueError("bad speaker")
        return store.split(job_id, int(segment_id), int(start), int(end), int(speaker))

    def detect_names(self, job_id: str) -> dict:
        _job(job_id)
        data, found = store.apply_detected_names(job_id)
        return {"job": data, "found": {str(k): v for k, v in found.items()}}

    # ---------------- settings ----------------
    def get_settings(self) -> dict:
        return {**asr.status(), "meeting_mode": bool(asr.get_settings().get("meeting_mode", False)), "language": asr.language_mode(),
                "learn_people": bool(asr.get_settings().get("learn_people", True)),
                "denoise": denoise.normalize_mode(asr.get_settings().get("denoise")),
                "denoise_ask": asr.get_settings().get("denoise_ask", True) is not False,
                "denoise_threshold": round(denoise.current_threshold(), 1),
                "denoise_answers": len(denoise.answers()),
                "tour_home_done": bool(asr.get_settings().get("tour_home_done", False)),
                "tour_job_done": bool(asr.get_settings().get("tour_job_done", False)),
                "update_check": updater.enabled(), **self._rec_settings()}

    def set_settings(self, values: dict) -> dict:
        if "use_gpu" in values:
            asr.set_use_gpu(bool(values["use_gpu"]))
        if values.get("ui_lang") in ("tr", "en"):
            asr.set_setting("ui_lang", values["ui_lang"])
        if "meeting_mode" in values:
            asr.set_setting("meeting_mode", bool(values["meeting_mode"]))
        if "learn_people" in values:
            asr.set_setting("learn_people", bool(values["learn_people"]))
        if values.get("denoise") in denoise.MODES:
            asr.set_setting("denoise", values["denoise"])
        if "denoise_ask" in values:
            asr.set_setting("denoise_ask", bool(values["denoise_ask"]))
        for key in ("tour_home_done", "tour_job_done"):
            if key in values:
                asr.set_setting(key, bool(values[key]))
        if values.get("language") in asr.LANGUAGES:
            asr.set_setting("language", values["language"])
        if "update_check" in values:
            asr.set_setting("update_check", bool(values["update_check"]))
        for key in ("rec_system", "rec_mic", "live_default", "rec_notice_done"):
            if key in values:
                asr.set_setting(key, bool(values[key]))
        if "rec_mic_id" in values:
            asr.set_setting("rec_mic_id", str(values["rec_mic_id"] or "")[:300])
        return self.get_settings()

    # ---------------- meeting recording (computer sound + microphone) ----------------
    LIVE_TEXT = False  # simple edition: no live text
    SIMPLE = True     # short minutes without analysis

    def _rec_settings(self) -> dict:
        s = asr.get_settings()
        return {"rec_system": s.get("rec_system", True) is not False, "rec_mic": s.get("rec_mic", True) is not False,
                "rec_mic_id": s.get("rec_mic_id") or "", "live_default": bool(s.get("live_default", False)),
                "rec_notice_done": bool(s.get("rec_notice_done", False))}

    def rec_devices(self) -> dict:
        from . import meeting_recorder

        return {"mics": meeting_recorder.list_mics(), "settings": self._rec_settings(), "live_available": self.LIVE_TEXT}

    def rec_status(self) -> dict:
        rec = getattr(self, "_rec", None)
        live = getattr(self, "_live", None)
        if not rec:
            return {"active": False}
        return {**rec.status(), "live": live.status() if live else None,
                "live_blocked": getattr(self, "_live_blocked", "")}

    def _live_transcribe(self, samples, duration) -> str:
        words, _ = asr.transcribe(samples, duration, lambda p: None)
        return "".join(w.text for w in words).strip()

    def _start_live(self) -> None:
        from . import meeting_recorder

        self._live_blocked = ""
        if not self.LIVE_TEXT:
            return
        if pipeline._current["id"]:  # a file is being transcribed: the model is busy
            self._live_blocked = "busy"
            return
        live = meeting_recorder.LiveWriter(self._live_transcribe)
        live._offset = self._rec.seconds() if getattr(self, "_rec", None) else 0.0
        self._live = live.start(self._rec.devices)

    def start_meeting(self, live: bool | None = None) -> dict:
        from . import meeting_recorder

        if getattr(self, "_rec", None):
            return self.rec_status()
        s = self._rec_settings()
        devices = meeting_recorder.open_devices(s["rec_system"], s["rec_mic"], s["rec_mic_id"] or None)
        if not devices:
            raise ValueError("no microphone or speaker was found")
        self._live = None
        self._rec = meeting_recorder.MeetingRecorder(devices, on_audio=self._feed_live)
        self._rec.start()
        if live if live is not None else s["live_default"]:
            self._start_live()
        return self.rec_status()

    def _feed_live(self, source, samples) -> None:
        live = getattr(self, "_live", None)
        if live:
            live.feed(source, samples)

    def set_live(self, on: bool) -> dict:
        if not getattr(self, "_rec", None):
            return {"active": False}
        live = getattr(self, "_live", None)
        if on and (not live or live.state != "running"):
            old = live.lines if live else []
            self._start_live()
            if getattr(self, "_live", None) and old and self._live is not live:
                self._live.lines = list(old)
        elif not on and live:
            live.stop()
        return self.rec_status()

    def pause_meeting(self, on: bool = True) -> dict:
        if getattr(self, "_rec", None):
            self._rec.pause(bool(on))
        return self.rec_status()

    def stop_meeting(self) -> dict:
        """Stop, mix and process the recording like a dropped file."""
        rec = getattr(self, "_rec", None)
        if not rec:
            return {"active": False}
        live = getattr(self, "_live", None)
        if live:
            live.stop()
        self._rec, self._live = None, None
        wav = rec.stop()
        return self._start_recording_job(wav)

    def cancel_meeting(self) -> dict:
        rec = getattr(self, "_rec", None)
        if getattr(self, "_live", None):
            self._live.stop()
        self._rec, self._live = None, None
        if rec:
            rec.cancel()
        return {"active": False}

    def _start_recording_job(self, wav: Path) -> dict:
        from . import meeting_recorder

        folder = wav.parent
        job_id = store.create_job(wav.name)
        store.update_job(job_id, source_path=str(wav), recorded=True)
        pipeline.enqueue(job_id)

        def run():
            run_job(job_id, wav, keep_source=True)
            if (store.job_path(job_id) / "audio.mp3").exists():  # the job has its own copy: drop the raw recording
                meeting_recorder.done(folder)
        threading.Thread(target=run, daemon=True).start()
        return {"id": job_id, "filename": wav.name}

    def rec_leftovers(self) -> list:
        from . import meeting_recorder

        return meeting_recorder.leftovers()

    def recover_recording(self, folder: str) -> dict:
        from . import meeting_recorder

        return self._start_recording_job(meeting_recorder.recover(folder))

    def discard_recording(self, folder: str) -> list:
        from . import meeting_recorder

        meeting_recorder.discard(folder)
        return meeting_recorder.leftovers()

    # ---------------- version and updates ----------------
    def get_app_info(self) -> dict:
        return {"version": version.VERSION, "edition": version.edition()}

    def check_update(self, force: bool = False, lang: str = "tr") -> dict:
        updater.check(bool(force))
        return updater.status(lang)

    def update_status(self, lang: str = "tr") -> dict:
        return updater.status(lang)

    def download_update(self, lang: str = "tr") -> dict:
        updater.download()
        return updater.status(lang)

    def snooze_update(self) -> dict:
        return updater.snooze()

    def install_update(self) -> dict:
        """Runs the downloaded setup after this window closes; the setup starts the new version."""
        return updater.install(lambda: self._window().destroy())


    # ---------------- meeting analysis ----------------
    def analyze_job(self, job_id: str) -> dict:
        from . import analysis

        _job(job_id)
        return analysis.start(job_id)

    def cancel_analysis(self, job_id: str) -> dict:
        from . import analysis

        _job(job_id)
        return analysis.cancel(job_id)

    def get_analysis(self, job_id: str) -> dict:
        from . import analysis

        _job(job_id)
        return analysis.status(job_id)

    # ---------------- export & files ----------------
    def _last_dir(self, key: str = "export_dir") -> str:
        d = asr.get_settings().get(key)
        return d if d and os.path.isdir(d) else str(Path.home() / "Documents")

    def _remember_dir(self, key: str, d: str) -> None:
        asr.set_setting(key, d)

    def save_word(self, job_id: str, lang: str = "tr") -> dict:
        """One click: the edited transcript as .docx. The Save dialog is pre-filled with the recording's name
        in the folder used last. Returns {"paths": [...]} or {"cancelled": True}."""
        import webview

        data = _job(job_id)
        chosen = _first(self._window().create_file_dialog(
            webview.FileDialog.SAVE, directory=self._last_dir(),
            save_filename=f"{_safe_name(Path(data['filename']).stem)}.docx", file_types=(EXPORT_TYPES["docx"],)))
        if not chosen:
            return {"cancelled": True}
        target = Path(chosen)
        if target.suffix.lower() != ".docx":
            target = target.with_name(target.name + ".docx")
        _write(target, export.render(data, "edited", "docx", lang))
        self._remember_dir("export_dir", str(target.parent))
        return {"paths": [str(target)]}

    # ---------------- meeting minutes (Settings page + "Minutes" button) ----------------
    def get_minutes_settings(self) -> dict:
        from . import minutes

        return {**minutes.config(), "logo_data": self._logo_data()}

    def _logo_data(self) -> str:
        import base64

        from . import minutes

        p = minutes.logo_path()
        if not p:
            return ""
        mime = "image/png" if p.suffix == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

    def set_minutes_settings(self, values: dict) -> dict:
        from . import minutes

        if "company_name" in values:
            asr.set_setting("company_name", str(values["company_name"] or "").strip()[:120])
        if "company_color" in values:
            asr.set_setting("company_color", minutes.clean_color(values["company_color"]))
        if "sections" in values:
            asr.set_setting("minutes_sections", minutes.clean_sections(values["sections"]))
        return self.get_minutes_settings()

    def pick_logo(self) -> dict:
        import webview

        from . import minutes

        f = _first(self._window().create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Picture (*.png;*.jpg;*.jpeg)",)))
        if f:
            minutes.set_logo(f)
        return self.get_minutes_settings()

    def remove_logo(self) -> dict:
        from . import minutes

        minutes.remove_logo()
        return self.get_minutes_settings()

    def pick_template(self) -> dict:
        import webview

        from . import minutes

        f = _first(self._window().create_file_dialog(
            webview.FileDialog.OPEN, directory=self._last_dir(), file_types=(EXPORT_TYPES["docx"],)))
        if f:
            minutes.set_template(f)
        return self.get_minutes_settings()

    def remove_template(self) -> dict:
        from . import minutes

        minutes.remove_template()
        return self.get_minutes_settings()

    def save_sample_template(self, lang: str = "tr") -> dict:
        """A starter Word template with every placeholder, to edit in Word and load back."""
        import webview

        from . import minutes

        chosen = _first(self._window().create_file_dialog(
            webview.FileDialog.SAVE, directory=self._last_dir(),
            save_filename="tutanak-sablonu.docx" if lang == "tr" else "minutes-template.docx",
            file_types=(EXPORT_TYPES["docx"],)))
        if not chosen:
            return {"cancelled": True}
        target = Path(chosen)
        if target.suffix.lower() != ".docx":
            target = target.with_name(target.name + ".docx")
        _write(target, minutes.sample_template(lang))
        self._remember_dir("export_dir", str(target.parent))
        return {"paths": [str(target)]}

    def save_minutes(self, job_id: str, lang: str = "tr") -> dict:
        """Meeting minutes as Word: the user's template when there is one, otherwise the built-in layout."""
        import json

        import webview

        from . import minutes

        data = _job(job_id)
        analysis = None
        path = store.job_path(job_id) / "analysis.json"
        if path.exists():
            try:
                analysis = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                analysis = None
        label = minutes.LABELS.get(lang, minutes.LABELS["tr"])["minutes"]
        chosen = _first(self._window().create_file_dialog(
            webview.FileDialog.SAVE, directory=self._last_dir(),
            save_filename=f"{_safe_name(Path(data['filename']).stem)} - {label}.docx", file_types=(EXPORT_TYPES["docx"],)))
        if not chosen:
            return {"cancelled": True}
        target = Path(chosen)
        if target.suffix.lower() != ".docx":
            target = target.with_name(target.name + ".docx")
        if self.SIMPLE:  # no analysis in the simple edition: who was there and what was said
            _write(target, minutes.build(data, None, lang, use_template=False, note_missing=False,
                                         sections=["participants", "transcript"]))
        else:
            _write(target, minutes.build(data, analysis, lang))
        self._remember_dir("export_dir", str(target.parent))
        return {"paths": [str(target)], "analysis": analysis is not None}

    # ---------------- folder watch (off by default) ----------------
    def get_watch(self) -> dict:
        return self._watcher.status()

    def pick_watch_folder(self) -> dict:
        import webview

        folder = _first(self._window().create_file_dialog(
            webview.FileDialog.FOLDER, directory=self._last_dir("watch_dir")))
        if folder:
            self._remember_dir("watch_dir", folder)
            self._watcher.set_dir(folder)
        return self._watcher.status()

    def set_watch(self, enabled: bool) -> dict:
        self._watcher.set_enabled(bool(enabled))
        return self._watcher.status()

    def save_export(self, job_id: str, version: str, fmt: str, lang: str = "en", speakers: list | None = None) -> dict:
        """Ask where to save, write the file(s). Returns {"paths": [...]} or {"cancelled": True}."""
        import json

        import webview

        if fmt not in EXPORT_TYPES or version not in ("original", "edited", "both", "analysis"):
            return {"error": "bad format"}
        data = _job(job_id)
        stem = _safe_name(Path(data["filename"]).stem)
        win = self._window()
        speakers = sorted({int(x) for x in speakers or []})
        if speakers and version != "analysis":  # only these people's lines: their names go into the file name
            stem += " - " + _safe_name(", ".join(export.speaker_names(data, speakers, lang)))

        if version == "analysis":  # a meeting analysis has no subtitles
            if fmt not in ("md", "txt", "docx", "json"):
                return {"error": "bad format"}
            path = store.job_path(job_id) / "analysis.json"
            if not path.exists():
                raise ValueError("this recording has no finished analysis yet")
            try:
                analysis = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                raise ValueError("the analysis file could not be read") from None
            suffix = "analiz" if lang == "tr" else "analysis"
            chosen = _first(win.create_file_dialog(
                webview.FileDialog.SAVE, directory=self._last_dir(),
                save_filename=f"{stem} - {suffix}.{fmt}", file_types=(EXPORT_TYPES[fmt],)))
            if not chosen:
                return {"cancelled": True}
            target = Path(chosen)
            if target.suffix.lower() != f".{fmt}":
                target = target.with_name(target.name + f".{fmt}")
            _write(target, export.render_analysis(data, analysis, fmt, lang))
            self._remember_dir("export_dir", str(target.parent))
            return {"paths": [str(target)]}

        versions = ["original", "edited"] if version == "both" else [version]
        if len(versions) == 1:
            path = _first(win.create_file_dialog(
                webview.FileDialog.SAVE, directory=self._last_dir(),
                save_filename=f"{stem}.{versions[0]}.{fmt}", file_types=(EXPORT_TYPES[fmt],)))
            if not path:
                return {"cancelled": True}
            target = Path(path)
            if target.suffix.lower() != f".{fmt}":
                target = target.with_name(target.name + f".{fmt}")
            targets = [target]
        else:  # both versions: pick a folder, write two files
            folder = _first(win.create_file_dialog(webview.FileDialog.FOLDER, directory=self._last_dir()))
            if not folder:
                return {"cancelled": True}
            targets = [Path(folder) / f"{stem}.{v}.{fmt}" for v in versions]
        for v, t in zip(versions, targets):
            _write(t, export.render(data, v, fmt, lang, speakers))
        self._remember_dir("export_dir", str(targets[0].parent))
        return {"paths": [str(t) for t in targets]}

    def reveal(self, path: str) -> None:
        """Open Explorer with the file selected."""
        p = Path(path)
        if not p.exists():
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])

    def open_url(self, url: str) -> None:
        """Open a web link in the user's normal browser (never inside the app window)."""
        import webbrowser

        if isinstance(url, str) and url.startswith(("https://", "http://")):
            webbrowser.open(url)

    # ---- people ----
    def list_people(self) -> list[dict]:
        from . import people

        return people.list_people()

    def create_person(self, name: str) -> dict:
        from . import people

        return people.create_person(name)

    def rename_person(self, person_id: str, name: str) -> dict:
        from . import people

        return people.rename_person(person_id, name)

    def delete_person(self, person_id: str) -> dict:
        from . import people

        people.delete_person(person_id)
        return {"ok": True}

    def add_person_sample_file(self, person_id: str | None = None, name: str | None = None) -> dict:
        """Native "Open" dialog, then add the chosen recording as a voice sample.
        person_id None + name: a new person is created once the sample is good enough."""
        import webview

        path = _first(self._window().create_file_dialog(
            webview.FileDialog.OPEN, directory=self._last_dir("open_dir"), file_types=MEDIA_TYPES))
        if not path:
            return {"cancelled": True}
        self._remember_dir("open_dir", str(Path(path).parent))
        return self._sample_from_path(path, person_id, name)

    def _sample_from_path(self, path: str, person_id: str | None, name: str | None) -> dict:
        from . import audio, people

        if person_id:
            return people.add_sample_from_file(person_id, path)
        if not (name or "").strip():
            raise ValueError("name required")
        speech = people.speech_only(audio.decode(Path(path))[0])
        if len(speech) / people.SR < people.MIN_SPEECH:  # nothing is created for a too short sample
            people.too_short(speech)
        pid = people.create_person(name)["id"]
        return people._enroll(pid, speech, "file:" + Path(path).name, people.MIN_SPEECH)

    def start_recording(self) -> dict:
        from . import people

        return people.start_recording()

    def recording_status(self) -> dict:
        from . import people

        return people.recording_status()

    def stop_recording(self, person_id: str | None = None, name: str | None = None) -> dict:
        from . import people

        return people.stop_recording(person_id, name)

    def cancel_recording(self) -> dict:
        from . import people

        return people.cancel_recording()

    def save_speaker_as_person(self, job_id: str, speaker: int, person_id: str | None = None,
                               name: str | None = None) -> dict:
        from . import people

        _job(job_id)
        return people.add_sample_from_job(job_id, int(speaker), person_id or None, name)

    # ---- glossary (names and terms the speech model spells wrong)
    def get_glossary(self) -> dict:
        from . import glossary

        return glossary.get()

    def set_glossary_terms(self, terms: list) -> dict:
        from . import glossary

        return glossary.set_terms([str(t) for t in terms])

    def add_glossary_fix(self, wrong: str, right: str) -> dict:
        from . import glossary

        return glossary.add_fix(str(wrong), str(right), manual=True)

    def remove_glossary_fix(self, wrong: str) -> dict:
        from . import glossary

        return glossary.remove_fix(str(wrong))

    def confirm_person(self, person_id: str) -> dict:
        from . import people

        return people.confirm_person(person_id)

    def rematch_job(self, job_id: str) -> dict:
        from . import people

        _job(job_id)
        return people.rematch_job(job_id)

    def accept_suggestion(self, job_id: str, speaker: int, person_id: str) -> dict:
        from . import people

        _job(job_id)
        return people.accept_suggestion(job_id, int(speaker), person_id)

    def accept_name_suggestion(self, job_id: str, speaker: int, name: str) -> dict:
        import json

        _job(job_id)
        name = name.strip()
        if not name:
            raise ValueError("empty name")
        job = store.save_edits(job_id, None, {int(speaker): name[:80]})
        path = store.job_path(job_id) / "analysis.json"
        try:
            data = json.loads(path.read_text("utf-8"))
            data["name_suggestions"] = [x for x in data.get("name_suggestions", []) if x.get("speaker") != int(speaker)]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        except (OSError, ValueError):
            pass
        return job
