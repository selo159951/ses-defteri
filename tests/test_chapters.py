"""Chapters and source links, with fake model output (no model needed)."""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import analysis, chapters, export, store  # noqa: E402

DATA = Path(__file__).parent / "data" / "meeting_tr.txt"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


def seg(i, spk, a, b, text):
    return {"id": i, "start": a, "end": b, "speaker": spk, "text_edited": text, "text_original": text, "words": []}


def meeting():
    out = []
    for ln in DATA.read_text("utf-8").splitlines():
        m = re.match(r"\[(\d+)\] \[(\d+):(\d+)-(\d+):(\d+)\] Konuşmacı (\d+): (.*)", ln)
        if m:
            i, a1, a2, b1, b2, spk, text = m.groups()
            out.append(seg(int(i), int(spk) - 1, int(a1) * 60 + int(a2), int(b1) * 60 + int(b2), text))
    return out


def ch(line, title, summary="Bu bölümde bir şeyler konuşuldu ve sonuçlandı."):
    return {"line": line, "title": title, "summary": summary}


# ---------- chapters: parsing ----------
def test_parse_moves_unknown_ids_to_the_nearest_real_one_and_sorts():
    ids = [10, 11, 12, 20, 21]
    got = chapters.parse({"chapters": [ch(21, "Son"), ch(13, "Orta"), ch(10, "Giriş"), ch(11, "Giriş 2"),
                                       ch("x", "Bozuk"), {"title": "Satırsız"}, ch(12, "  ")]}, ids)
    assert [c["line"] for c in got] == [10, 11, 12, 21]  # 13 -> 12 (nearest), "Orta" kept because 12 was free
    assert got[2]["title"] == "Orta"
    assert chapters.parse("not a dict", ids) == [] and chapters.parse({"chapters": [ch(1, "x")]}, []) == []


def test_parse_keeps_one_chapter_per_line():
    got = chapters.parse({"chapters": [ch(5, "Birinci"), ch(5, "İkinci")]}, [5, 6])
    assert [c["title"] for c in got] == ["Birinci"]


# ---------- chapters: assembling ----------
def test_assemble_times_first_covers_the_start_and_last_ends_with_the_recording():
    segs = meeting()
    out = chapters.assemble([ch(2, "Kapsam"), ch(19, "Tarih"), ch(35, "Görevler")], segs, 5)
    assert [c["title"] for c in out] == ["Kapsam", "Tarih", "Görevler"]
    assert out[0]["start"] == 0 and out[0]["line"] == 1  # starts with the recording even if cited at line 2
    assert (out[1]["start"], out[1]["end"]) == (142, 267) and out[2]["end"] == 600
    assert all(a["end"] == b["start"] for a, b in zip(out, out[1:]))


def test_assemble_merges_same_title_neighbours_but_not_related_ones():
    segs = meeting()
    same = chapters.assemble([ch(1, "Sürüm Tarihi", "Birinci cümle burada."), ch(19, "sürüm tarihi", "İkinci cümle burada."),
                              ch(35, "Görevler")], segs, 5)
    assert [c["title"] for c in same] == ["Sürüm Tarihi", "Görevler"]
    assert "Birinci" in same[0]["summary"] and "İkinci" in same[0]["summary"]
    related = chapters.assemble([ch(1, "Sürüm Kapsamı"), ch(19, "Sürüm Tarihi"), ch(35, "Görevler")], segs, 5)
    assert len(related) == 3


def test_assemble_folds_short_chapters_into_the_previous_one():
    segs = meeting()
    out = chapters.assemble([ch(1, "Kapsam"), ch(19, "Tarih"), ch(28, "Öğle"), ch(35, "Görevler")], segs, 6)
    # lines 28-34 last 54 s (< 60 s): folded into "Tarih", which is then long enough to stay
    assert [c["title"] for c in out] == ["Kapsam", "Tarih", "Görevler"]
    assert out[1]["end"] == out[2]["start"] == 267
    first_short = chapters.assemble([ch(1, "Selam"), ch(3, "Gündem"), ch(35, "Görevler")], segs, 6)
    assert first_short[0]["start"] == 0 and first_short[0]["title"] == "Gündem"  # the first one disappears into the next


def test_assemble_respects_the_maximum_and_short_meetings():
    segs = meeting()
    many = [ch(1, "Kapsam"), ch(19, "Tarih"), ch(35, "Görevler"), ch(53, "Metinler"), ch(62, "Riskler")]
    assert len(chapters.assemble(many, segs, 3)) == 3
    assert chapters.assemble(many, segs, 0) == []
    assert chapters.max_chapters(90) == 0 and chapters.max_chapters(200) == 2 and chapters.max_chapters(600) >= 4
    assert chapters.assemble([], segs, 3) == [] and chapters.assemble(many, [], 3) == []


# ---------- chapters: build with a fake model, in windows ----------
def test_build_short_meeting_makes_no_call():
    segs = [seg(i, 0, i * 8, i * 8 + 8, "Merhaba, kısa bir toplantı yapıyoruz.") for i in range(1, 8)]  # 56 s
    calls = []
    assert chapters.build(segs, analysis.render(segs, {"0": "A"}), "tr", lambda *a, **k: calls.append(a)) == []
    assert not calls


def test_build_reads_in_windows_and_hands_the_last_title_to_the_next():
    segs = meeting()
    lines = analysis.render(segs, {"0": "Deniz", "1": "Burak", "2": "Elif"})
    prompts = []

    def fake(prompt, schema, max_tokens=0):
        prompts.append(prompt)
        first = int(re.search(r"^\[(\d+)\]", prompt, re.M).group(1))
        return {"chapters": [ch(first, "Birinci konu" if first == 1 else "Başka konu"), ch(first + 20, "Orta konu" + str(first))]}

    assert chapters.build(segs, lines, "tr", fake) and len(prompts) == 1  # one window for ten minutes
    old = chapters.WINDOW_TOKENS
    try:
        chapters.WINDOW_TOKENS = 400  # several windows
        prompts.clear()
        out = chapters.build(segs, lines, "tr", fake)
    finally:
        chapters.WINDOW_TOKENS = old
    assert len(prompts) > 2
    assert "Önceki bölümün son konusu" not in prompts[0] and "Önceki bölümün son konusu" in prompts[1]
    assert all(a["end"] == b["start"] for a, b in zip(out, out[1:])) and out[-1]["end"] == 600


def test_build_drops_invented_numbers_in_summaries():
    segs = meeting()
    lines = analysis.render(segs, {"0": "Deniz", "1": "Burak", "2": "Elif"})
    fake = lambda p, s, max_tokens=0: {"chapters": [ch(1, "Kapsam", "Sürüm 2.4 planlandı. Sürüm 9.9 çıktı.")]}  # noqa: E731
    out = chapters.build(segs, lines, "tr", fake)
    assert out[0]["summary"] == "Sürüm 2.4 planlandı."


# ---------- chapters inside the analysis run ----------
class Fake:
    def __init__(self, with_chapters=True, boom=False):
        self.calls, self.with_chapters, self.boom = [], with_chapters, boom

    def __call__(self, prompt, schema=None, **kw):
        self.calls.append(schema)
        props = (schema or {}).get("properties", {})
        if "chapters" in props:
            if self.boom:
                raise RuntimeError("model broke")
            return {"chapters": [ch(1, "Kapsam"), ch(19, "Tarih"), ch(35, "Görevler")]} if self.with_chapters else {}
        if "summary" in props:
            return {"summary": "ozet"}
        return {"topics": [], "decisions": []}


def make_job(segs):
    job_id = store.create_job("m.mp3")
    store.update_job(job_id, status="done", segments=segs, speakers={"0": "Deniz", "1": "Burak", "2": "Elif"}, language="tr")
    return job_id


def test_run_writes_chapters_and_reuses_them(monkeypatch):
    jid = make_job(meeting())
    f = Fake()
    analysis.run(jid, generate=f)
    a = json.loads((store.job_path(jid) / "analysis.json").read_text("utf-8"))
    assert [c["title"] for c in a["chapters"]] == ["Kapsam", "Tarih", "Görevler"]
    n = sum(1 for s in f.calls if s and "chapters" in s["properties"])
    assert n == 1
    f2 = Fake()
    analysis.run(jid, generate=f2)  # same transcript: chapters come from analysis/chapters.json
    assert not any(s and "chapters" in s["properties"] for s in f2.calls)
    assert json.loads((store.job_path(jid) / "analysis.json").read_text("utf-8"))["chapters"] == a["chapters"]


def test_failed_chapters_cost_only_the_chapters():
    jid = make_job(meeting())
    analysis.run(jid, generate=Fake(boom=True))
    a = json.loads((store.job_path(jid) / "analysis.json").read_text("utf-8"))
    assert a["chapters"] == [] and any("chapters" in w for w in a["warnings"])
    assert store.read_transcript(jid)["analysis"]["state"] == "done"


def test_export_has_chapters_and_marks_missing_sources():
    job = {"filename": "m.mp3", "speakers": {"0": "Deniz"}, "segments": [seg(1, 0, 0, 10, "a"), seg(2, 0, 3725, 3730, "b")]}
    a = {"chapters": [{"title": "Kapsam", "summary": "Bir cümle burada.", "start": 0, "end": 3725, "line": 1}],
         "topics": [{"title": "Eski", "summary": "", "start": 0, "end": 5}],
         "decisions": [{"text": "Karar bir", "line": 2, "source_ok": True}, {"text": "Karar iki", "line": 1, "source_ok": False}]}
    md = export.render_analysis(job, a, "md", "tr")
    assert "## Bölümler" in md and "[00:00:00 – 01:02:05] Kapsam" in md and "Eski" not in md
    assert "Karar bir [01:02:05]" in md and "Karar iki [kaynak bulunamadı]" in md


# ---------- source links ----------
def pp(raw, segs=None):
    segs = segs or meeting()
    st = analysis.stats(segs, {"0": "Deniz", "1": "Burak", "2": "Elif"})
    return analysis.postprocess(raw, segs, st, {"deniz": 0, "burak": 1, "elif": 2}, [], "tr")


def test_source_ok_when_the_cited_line_says_it():
    out = pp({"decisions": [{"text": "Zamanlanmış bildirimler 2.5'e bırakılacak.", "line": 18}],
              "tasks": [{"owner": "Elif", "task": "Push altyapısı dokümantasyonunu hazırlamak", "due": "Cuma", "line": 39}],
              "open_questions": [{"asker": "Elif", "text": "Bildirim metinlerini kim yazacak?", "line": 55}]})
    assert out["decisions"][0]["line"] in (16, 18) and out["decisions"][0]["source_ok"] is True
    assert out["tasks"][0]["source_ok"] is True and out["open_questions"][0]["source_ok"] is True


def test_source_not_found_is_flagged_not_hidden():
    out = pp({"decisions": [{"text": "Müşteri sözleşmesi imzalanacak.", "line": 3}]})
    d = out["decisions"][0]
    assert d["source_ok"] is False and d["line"] == 3  # kept, marked


def test_nonexistent_line_is_repaired_by_searching_or_flagged():
    fixed = pp({"decisions": [{"text": "Feature freeze sürümden bir hafta önce olacak.", "line": 9999}]})
    assert fixed["decisions"][0]["line"] in (50, 51, 52) and fixed["decisions"][0]["source_ok"] is True
    lost = pp({"tasks": [{"owner": "Burak", "task": "Kuantum bilgisayarı kurmak", "due": "", "line": 9999}]})
    t = lost["tasks"][0]
    assert t["line"] is None and t["source_ok"] is False and t["owner"] == 1


def test_source_ok_helper_edge_cases():
    segs = meeting()
    pos = {s["id"]: i for i, s in enumerate(segs)}
    assert analysis._source("x", "Bildirimler dar kapsamlı olsun", segs, pos)[1] is True  # non-numeric id: searched
    assert analysis._source(None, "ab", segs, pos) == (None, False) or analysis._source(None, "ab", segs, pos)[1] is True
    assert analysis._source(2, "", segs, pos) == (2, True)  # nothing to compare
