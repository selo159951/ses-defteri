"""Folder watch (complete files only, never twice) and "only one person's words" export. Synthetic data only."""
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import asr, bridge, export, watcher  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))


# ---------------------------------------------------------------- folder watch
@pytest.mark.parametrize("name,ok", [
    ("toplanti.mp3", True), ("Kayit 1.WAV", True), ("a.m4a", True), ("v.MP4", True), ("x.webm", True),
    ("toplanti.mp3.part", False), ("toplanti.tmp", False), ("~$notlar.docx", False), ("~toplanti.mp3", False),
    (".hidden.mp3", False), ("notlar.txt", False), ("resim.png", False), ("toplanti.mp3.crdownload", False),
    ("toplanti", False), ("a.mp3~", False),
])
def test_is_candidate(name, ok):
    assert watcher.is_candidate(name) is ok


class Env:
    def __init__(self, tmp_path):
        self.folder = tmp_path / "izle"
        self.folder.mkdir()
        self.started = []
        self.w = watcher.Watcher(self._start, stable_secs=5)
        asr.set_setting("watch_dir", str(self.folder))
        asr.set_setting("watch_enabled", True)
        asr.set_setting("watch_since", 0)

    def _start(self, paths):
        self.started += paths
        return [{"id": "x"} for _ in paths]

    def tick(self, now):
        return self.w.tick(now)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_default_is_off(tmp_path):
    w = watcher.Watcher(lambda p: [])
    assert w.config()["enabled"] is False
    assert w.status()["note"] == ""
    assert w.scan() == []


def test_waits_until_size_is_stable(env):
    f = env.folder / "toplanti.wav"
    f.write_bytes(b"a" * 100)
    env.tick(100)           # first sight
    f.write_bytes(b"a" * 200)
    env.tick(103)           # grew: counter restarts
    env.tick(107)           # only 4 s since it last changed
    assert env.started == []
    env.tick(109)           # 6 s of no change
    assert env.started == [str(f)]


def test_never_processed_twice(env):
    f = env.folder / "toplanti.mp3"
    f.write_bytes(b"x" * 50)
    for t in (10, 11, 20, 30, 40, 50):
        env.tick(t)
    assert env.started == [str(f)]
    # a second watcher (app restart) knows it too
    w2 = watcher.Watcher(env._start, stable_secs=5)
    for t in (60, 70, 80):
        w2.tick(t)
    assert env.started == [str(f)]


def test_changed_file_with_same_name_is_a_new_file(env):
    f = env.folder / "kayit.mp3"
    f.write_bytes(b"x" * 50)
    for t in (10, 20):
        env.tick(t)
    f.write_bytes(b"y" * 80)
    for t in (30, 40):
        env.tick(t)
    assert env.started == [str(f), str(f)]


def test_ignores_temp_other_types_empty_files_and_subfolders(env):
    (env.folder / "a.mp3.part").write_bytes(b"x")
    (env.folder / "~$b.mp3").write_bytes(b"x")
    (env.folder / "notlar.txt").write_bytes(b"x")
    (env.folder / "bos.mp3").write_bytes(b"")
    sub = env.folder / "alt"
    sub.mkdir()
    (sub / "c.mp3").write_bytes(b"x" * 9)
    for t in (10, 20, 30):
        env.tick(t)
    assert env.started == []


def test_files_present_before_switching_on_are_not_taken(env):
    f = env.folder / "eski.mp3"
    f.write_bytes(b"x" * 10)
    os.utime(f, (1000, 1000))
    asr.set_setting("watch_since", 2_000_000_000)  # in the future of the file's times
    for t in (10, 20, 30):
        env.tick(t)
    assert env.started == []


def test_missing_folder_gives_a_note_and_resumes(env, tmp_path):
    gone = tmp_path / "usb"
    asr.set_setting("watch_dir", str(gone))
    assert env.tick(10) == []
    assert env.w.status()["note"] == "missing"
    gone.mkdir()
    (gone / "yeni.mp3").write_bytes(b"x" * 10)
    for t in (20, 30, 40):
        env.tick(t)
    assert env.started == [str(gone / "yeni.mp3")]
    assert env.w.status()["note"] == ""


def test_turned_off_does_nothing(env):
    asr.set_setting("watch_enabled", False)
    (env.folder / "a.mp3").write_bytes(b"x" * 10)
    for t in (10, 20, 30):
        env.tick(t)
    assert env.started == []
    assert env.w.status()["note"] == ""


def test_set_enabled_needs_folder_and_toggles(tmp_path):
    w = watcher.Watcher(lambda p: [])
    with pytest.raises(ValueError):
        w.set_enabled(True)
    w.set_dir(str(tmp_path))
    w.set_enabled(True)
    assert w.status()["enabled"] and w.status()["dir"] == str(tmp_path)
    w.set_enabled(False)
    assert not w.status()["enabled"]


def test_bridge_exposes_watch_and_default_off():
    api = bridge.Api()
    assert api.get_watch()["enabled"] is False


def test_tick_counts_started_jobs(env):
    (env.folder / "a.mp3").write_bytes(b"x" * 10)
    for t in (10, 20):
        env.tick(t)
    st = env.w.status()
    assert st["queued"] == 1 and st["last_file"] == "a.mp3"


# ---------------------------------------------------------------- one person's words
def job():
    seg = lambda i, a, b, spk, text: {"id": i, "start": a, "end": b, "speaker": spk, "text_original": text,
                                      "text_edited": text}
    return {"filename": "toplanti.wav", "language": "tr", "speakers": {"0": "Deniz", "1": "Burak", "2": "Elif"},
            "segments": [seg(0, 0.0, 2.5, 0, "Merhaba herkese."), seg(1, 2.5, 5.0, 1, "Günaydın Deniz."),
                         seg(2, 5.0, 8.0, 0, "Gündemi açıyorum."), seg(3, 8.0, 9.0, 2, "Ben de varım."),
                         seg(4, 9.0, 10.0, 1, "   ")]}


def test_rows_filter_one_and_several_speakers():
    d = job()
    assert [r["text"] for r in export.rows(d, "edited", "tr", [0])] == ["Merhaba herkese.", "Gündemi açıyorum."]
    assert {r["speaker"] for r in export.rows(d, "edited", "tr", [1, 2])} == {"Burak", "Elif"}
    assert len(export.rows(d, "edited", "tr")) == 4          # everybody
    assert len(export.rows(d, "edited", "tr", [])) == 4      # none ticked = everybody
    assert export.rows(d, "edited", "tr", [7]) == []


def test_filter_works_on_original_version_too():
    d = job()
    assert [r["text"] for r in export.rows(d, "original", "en", ["2"])] == ["Ben de varım."]


def test_speaker_names_default_labels_follow_language():
    d = job()
    d["speakers"] = {}
    assert export.speaker_names(d, [0, 1], "tr") == ["Konuşmacı 1", "Konuşmacı 2"]
    assert export.speaker_names(d, [0], "en") == ["Speaker 1"]


def test_srt_has_times_and_only_that_person():
    out = export.render(job(), "edited", "srt", "tr", [0])
    assert "00:00:00,000 --> 00:00:02,500" in out and "00:00:05,000 --> 00:00:08,000" in out
    assert "Burak" not in out and "Elif" not in out and out.count("Deniz:") == 2
    assert out.startswith("1\n")


def test_json_lists_only_speakers_and_segments():
    d = json.loads(export.render(job(), "edited", "json", "tr", [1]))
    assert d["only_speakers"] == ["Burak"]
    assert [s["text"] for s in d["segments"]] == ["Günaydın Deniz."]
    assert d["segments"][0]["start"] == 2.5
    assert "only_speakers" not in json.loads(export.render(job(), "edited", "json", "tr"))


def test_markdown_and_txt_only_one():
    md = export.render(job(), "edited", "md", "tr", [2])
    assert "*Elif*" in md and "Ben de varım." in md and "Deniz`" not in md and "Merhaba" not in md
    txt = export.render(job(), "edited", "txt", "tr", [2])
    assert "Elif:" in txt and "Deniz" not in txt.replace("Günaydın Deniz", "")


def test_docx_only_one_person():
    from docx import Document

    data = export.render(job(), "edited", "docx", "tr", [0, 2])
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Deniz, Elif" in text and "Merhaba herkese." in text and "Günaydın" not in text
    assert "00:00:00" in text  # times kept


def test_docx_everybody_unchanged_header():
    from docx import Document

    doc = Document(io.BytesIO(export.render(job(), "edited", "docx", "tr")))
    assert any("4 satır" in p.text for p in doc.paragraphs)


class FakeWin:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create_file_dialog(self, kind, **kw):
        self.calls.append(kw)
        return self.answer


def api_with_job(tmp_path, answer):
    from backend import store

    jid = store.create_job("Haftalik: toplanti.wav")
    d = job()
    d["filename"] = "Haftalik: toplanti.wav"
    store.write_transcript(jid, {**store.read_transcript(jid), **d})
    win = FakeWin(answer)
    return bridge.Api(lambda: win), jid, win


def test_save_word_one_step_prefilled_name(tmp_path):
    target = tmp_path / "out" / "kayit"
    target.parent.mkdir()
    api, jid, win = api_with_job(tmp_path, str(target))
    r = api.save_word(jid, "tr")
    assert r["paths"] == [str(target) + ".docx"]
    assert Path(r["paths"][0]).read_bytes()[:2] == b"PK"
    assert win.calls[0]["save_filename"] == "Haftalik_ toplanti.docx"  # illegal character removed
    # next time the dialog opens in the folder used last
    api.save_word(jid, "tr")
    assert win.calls[1]["directory"] == str(target.parent)


def test_save_word_cancel(tmp_path):
    api, jid, _ = api_with_job(tmp_path, None)
    assert api.save_word(jid) == {"cancelled": True}


def test_save_export_person_name_in_file_name(tmp_path):
    target = tmp_path / "x.srt"
    api, jid, win = api_with_job(tmp_path, str(target))
    r = api.save_export(jid, "edited", "srt", "tr", [0])
    assert win.calls[0]["save_filename"] == "Haftalik_ toplanti - Deniz.edited.srt"
    out = Path(r["paths"][0]).read_text("utf-8")
    assert "Deniz" in out and "Burak" not in out
    api.save_export(jid, "edited", "md", "tr", [0, 1])
    assert win.calls[1]["save_filename"] == "Haftalik_ toplanti - Deniz, Burak.edited.md"


def test_save_export_without_speakers_is_unchanged(tmp_path):
    target = tmp_path / "x.json"
    api, jid, win = api_with_job(tmp_path, str(target))
    api.save_export(jid, "edited", "json", "tr")
    assert win.calls[0]["save_filename"] == "Haftalik_ toplanti.edited.json"
    assert len(json.loads(target.read_text("utf-8"))["segments"]) == 4
