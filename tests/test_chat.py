"""AI assistant: dates from Turkish/English words, local search database, rules (no invented sources, off-topic
refused, nothing found -> no model call). The language model is a fake. Synthetic data only."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import chat, chatdb, store  # noqa: E402

NOW = dt.datetime(2026, 11, 19, 15, 0)  # a Thursday
MON = dt.date(2026, 11, 16)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))


def ts(d: dt.date, h=10) -> float:
    return dt.datetime.combine(d, dt.time(h)).timestamp()


def make_job(name, when, lines, speakers, analysis=None, status="done"):
    jid = store.create_job(name)
    segs = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 9, "speaker": s, "text_original": t, "text_edited": t}
            for i, (s, t) in enumerate(lines)]
    store.update_job(jid, status=status, created=when, duration=len(lines) * 10.0, speakers=speakers, segments=segs)
    if analysis:
        (store.job_path(jid) / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), "utf-8")
    return jid


@pytest.fixture
def data():
    last_week = make_job("Haftalik.mp3", ts(MON - dt.timedelta(days=5)), [
        (0, "Günaydın, uygulamanın yeni sürümünü konuşalım."),
        (1, "Uygulamada ödeme ekranı hâlâ yavaş, bunu düzeltmeliyiz."),
        (0, "Tamam, fiyatları da artıracağız."),
        (1, "Testleri cuma bitiririm."),
    ], {"0": "Ayşe", "1": "Ahmet Yılmaz"}, {
        "summary": "Uygulamanın sürümü ve ödeme ekranı konuşuldu.",
        "decisions": [{"text": "Fiyatlar artırılacak", "line": 2}],
        "tasks": [{"owner": 1, "task": "Testleri bitir", "due": "Cuma", "line": 3}],
    })
    this_week = make_job("Planlama.mp3", ts(MON + dt.timedelta(days=1)), [
        (0, "Bütçeyi konuşalım."), (1, "Uygulama için iki kişi daha lazım."),
    ], {"0": "Ayşe", "1": "Ahmet Yılmaz"})
    make_job("Yarim.mp3", ts(MON), [(0, "Bu iş daha bitmedi uygulama")], {"0": "Ayşe"}, status="running")
    return {"last": last_week, "this": this_week}


class FakeLLM:
    def __init__(self, intent, answer=None):
        self.intent, self.answer, self.calls = intent, answer, []

    def __call__(self, prompt, schema=None, system=None, **kw):
        self.calls.append({"prompt": prompt, "schema": schema, "system": system})
        if schema is chat.INTENT_SCHEMA:
            return dict(self.intent)
        if schema is chat.ANSWER_SCHEMA:
            return dict(self.answer) if callable(self.answer) is False else self.answer(prompt)
        return "Ses Defteri'yi Selim Oğuz geliştirdi."


# ---------------------------------------------------------------- dates
@pytest.mark.parametrize("q,a,b", [
    ("geçen hafta ne konuştuk", MON - dt.timedelta(days=7), MON),
    ("Geçen haftaki toplantıda", MON - dt.timedelta(days=7), MON),
    ("bu hafta", MON, dt.date(2026, 11, 20)),
    ("dün ne dedi", dt.date(2026, 11, 18), dt.date(2026, 11, 19)),
    ("bugün", dt.date(2026, 11, 19), dt.date(2026, 11, 20)),
    ("3 gün önce", dt.date(2026, 11, 16), dt.date(2026, 11, 17)),
    ("2 hafta önce", MON - dt.timedelta(days=14), MON - dt.timedelta(days=7)),
    ("son 10 gün", dt.date(2026, 11, 10), dt.date(2026, 11, 20)),
    ("geçen ay", dt.date(2026, 10, 1), dt.date(2026, 11, 1)),
    ("bu ay", dt.date(2026, 11, 1), dt.date(2026, 11, 20)),
    ("12 kasım toplantısı", dt.date(2026, 11, 12), dt.date(2026, 11, 13)),
    ("05.10.2026", dt.date(2026, 10, 5), dt.date(2026, 10, 6)),
    ("geçen salı", dt.date(2026, 11, 10), dt.date(2026, 11, 11)),
    ("salı günü", dt.date(2026, 11, 17), dt.date(2026, 11, 18)),
    ("last week", MON - dt.timedelta(days=7), MON),
    ("yesterday", dt.date(2026, 11, 18), dt.date(2026, 11, 19)),
])
def test_resolve_dates(q, a, b):
    r = chat.resolve_dates(q, NOW)
    assert r is not None, q
    assert (dt.date.fromtimestamp(r[0]), dt.date.fromtimestamp(r[1])) == (a, b)


@pytest.mark.parametrize("q", ["sürüm cuma çıkacak mı", "1.5 milyon bütçe", "Ahmet ne dedi"])
def test_no_date_words(q):
    assert chat.resolve_dates(q, NOW) is None


def test_last_week_over_new_year():
    r = chat.resolve_dates("geçen hafta", dt.datetime(2027, 1, 2))
    assert dt.date.fromtimestamp(r[0]) == dt.date(2026, 12, 21)


def test_last_month_in_january():
    r = chat.resolve_dates("geçen ay", dt.datetime(2027, 1, 15))
    assert dt.date.fromtimestamp(r[0]) == dt.date(2026, 12, 1)


# ---------------------------------------------------------------- database
@pytest.mark.parametrize("word,st", [("uygulamayı", "uygulam"), ("toplantıdaki", "toplant"), ("Ahmet'in", "ahmet"),
                                     ("kararlar", "karar"), ("zam", "zam")])
def test_stem(word, st):
    assert chatdb.stem(word) == st


def test_sync_indexes_only_finished_and_follows_changes(data):
    assert chatdb.sync() == 2
    assert chatdb.counts()["recordings"] == 2
    assert chatdb.sync() == 0  # nothing changed
    store.delete_job(data["this"])
    chatdb.sync()
    assert chatdb.counts()["recordings"] == 1


def test_search_by_word_person_and_date(data):
    chatdb.sync()
    a, b, _ = chat.resolve_dates("geçen hafta", NOW)
    rows = chatdb.search(["uygulamada"], a, b, chatdb.people_in(["ahmet"]), ["line"])
    assert [r["text"] for r in rows] == ["Uygulamada ödeme ekranı hâlâ yavaş, bunu düzeltmeliyiz."]
    assert chatdb.search(["uygulama"], *chat.resolve_dates("bu hafta", NOW)[:2], None, ["line"])[0]["filename"] == "Planlama.mp3"


def test_analysis_items_are_searchable(data):
    chatdb.sync()
    rows = chatdb.search(None, kinds=["decision"])
    assert rows[0]["text"] == "Fiyatlar artırılacak" and rows[0]["start"] == 20.0
    task = chatdb.search(None, kinds=["task"])[0]
    assert task["speaker"] == "Ahmet Yılmaz" and "Cuma" in task["text"]


def test_people_match_ignores_case_letters_and_surname(data):
    chatdb.sync()
    assert chatdb.people_in(["AHMET"]) == ["Ahmet Yılmaz"]
    assert chatdb.people_in(["ayse"]) == ["Ayşe"]
    assert chatdb.people_in(["Mehmet"]) == []


# ---------------------------------------------------------------- whole question
def test_question_answered_with_checked_sources(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": ["Ahmet"], "anahtar": ["uygulama"]},
                  {"cevap": "Ahmet ödeme ekranının yavaş olduğunu söyledi [1].", "kaynaklar": [1, 1, 99], "bulundu": True})
    r = chat.ask("Geçen hafta Ahmet uygulama için ne demişti?", lang="tr", generate=llm, people=[], now=NOW)
    assert r["found"] and r["answer"] == "Ahmet ödeme ekranının yavaş olduğunu söyledi."
    assert [s["n"] for s in r["sources"]] == [1]  # 99 does not exist, the repeat is dropped
    s = r["sources"][0]
    assert s["filename"] == "Haftalik.mp3" and s["start"] == 10.0 and s["speaker"] == "Ahmet Yılmaz"
    # the model saw today's date, the date range and only last week's lines
    ans = llm.calls[1]
    assert "19.11.2026" in ans["system"] and "Planlama.mp3" not in ans["prompt"] and "Haftalik.mp3" in ans["prompt"]
    assert "09.11.2026 – 15.11.2026" in r["range"]


def test_nothing_found_means_no_answer_call(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": ["helikopter"]})
    r = chat.ask("helikopterden bahsettik mi", generate=llm, people=[], now=NOW)
    assert not r["found"] and "bulamadım" in r["answer"] and len(llm.calls) == 1


def test_unknown_person_finds_nothing(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": ["Mehmet"], "anahtar": ["uygulama"]})
    r = chat.ask("Mehmet ne dedi", generate=llm, people=[], now=NOW)
    assert not r["found"] and len(llm.calls) == 1


def test_off_topic_is_refused_without_search(data):
    llm = FakeLLM({"niyet": "kapsam_disi", "tur": "genel", "kisiler": [], "anahtar": []})
    r = chat.ask("Bana bir şiir yaz", generate=llm, people=[], now=NOW)
    assert r["answer"].startswith("Bu konuda yardımcı olamıyorum") and len(llm.calls) == 1


def test_app_question_uses_fixed_facts(data):
    llm = FakeLLM({"niyet": "uygulama", "tur": "genel", "kisiler": [], "anahtar": []})
    r = chat.ask("Bu programı kim yaptı?", generate=llm, people=[], now=NOW)
    assert "Selim Oğuz" in r["answer"]
    assert "Umut Akbaş" in llm.calls[1]["system"] and "Selim Oğuz" in llm.calls[1]["system"]


def test_decisions_question_uses_analysis(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "karar", "kisiler": [], "anahtar": []},
                  {"cevap": "Fiyatlar artırılacak.", "kaynaklar": [1], "bulundu": True})
    r = chat.ask("Geçen hafta hangi kararlar alındı?", generate=llm, people=[], now=NOW)
    assert r["sources"][0]["kind"] == "decision"
    assert "karar" in llm.calls[1]["prompt"]


def test_follow_up_keeps_the_dates(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": ["Ayşe"], "anahtar": ["uygulama"]},
                  {"cevap": "Ayşe yeni sürümü konuşmak istedi.", "kaynaklar": [1], "bulundu": True})
    first = chat.resolve_dates("geçen hafta", NOW)
    hist = [{"q": "Geçen hafta Ahmet ne dedi?", "range_ts": [first[0], first[1]], "range": "geçen hafta"}]
    r = chat.ask("Peki Ayşe?", history=hist, generate=llm, people=[], now=NOW)
    assert r["sources"] and r["sources"][0]["filename"] == "Haftalik.mp3"
    assert "Önceki soru: Geçen hafta Ahmet ne dedi?" in llm.calls[0]["prompt"]


def test_people_titles_reach_the_model(data):
    llm = FakeLLM({"niyet": "kapsam_disi", "tur": "genel", "kisiler": [], "anahtar": []})
    chat.ask("x", generate=llm, now=NOW, people=[{"name": "Ahmet Yılmaz", "title": "Proje yöneticisi", "note": "mobil"}])
    assert "Ahmet Yılmaz — Proje yöneticisi — mobil" in llm.calls[0]["system"]


def test_no_recordings_yet():
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": ["x"]})
    assert "Henüz" in chat.ask("x ne oldu", generate=llm, people=[], now=NOW)["answer"]


# ---------------------------------------------------------------- what the code decides itself
@pytest.mark.parametrize("q,kind", [("Bugün Mehmet ne demişti?", "genel"), ("Hangi kararlar alındı?", "karar"),
                                    ("Ahmet'in görevleri neler?", "gorev"), ("Açık sorular kaldı mı?", "soru"),
                                    ("Geçen hafta neler konuşuldu?", "ozet"), ("What were the decisions?", "karar")])
def test_kind_of_question(q, kind):
    assert chat.kind_of_question(q) == kind


def test_clean_words_drops_filler_and_names():
    assert chat.clean_words(["dedi", "ne", "toplantı", "uygulama", "Ahmet", "ödeme ekranı"], ["Ahmet"]) == ["uygulama", "ödeme ekranı"]


def test_bugunku_is_today():
    r = chat.resolve_dates("Bugünkü toplantıda ne oldu", NOW)
    assert dt.date.fromtimestamp(r[0]) == dt.date(2026, 11, 19)


@pytest.mark.parametrize("raw,clean", [("**Umut Akbaş** ve *Selim*", "Umut Akbaş ve Selim"), ("Ses Defeti'ni", "Ses Defteri'ni"),
                                       ("2*3 = 6", "2*3 = 6"), ("Ahmet testleri yazacak. Kaynak:", "Ahmet testleri yazacak.")])
def test_tidy(raw, clean):
    assert chat.tidy(raw) == clean


def test_model_reading_ne_demisti_as_questions_is_overruled(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "soru", "kisiler": ["Ahmet"], "anahtar": ["dedi", "ne"]},
                  {"cevap": "Ahmet testleri cuma bitireceğini söyledi.", "kaynaklar": [1], "bulundu": True})
    r = chat.ask("Geçen hafta Ahmet ne demişti?", generate=llm, people=[], now=NOW)
    assert r["intent"]["tur"] == "genel" and r["intent"]["anahtar"] == []
    assert r["sources"][0]["kind"] == "line" and r["sources"][0]["speaker"] == "Ahmet Yılmaz"


def test_made_up_words_fall_back_to_the_persons_lines(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": ["Ahmet"], "anahtar": ["helikopter"]},
                  {"cevap": "Ahmet ödeme ekranının yavaş olduğunu söyledi.", "kaynaklar": [1], "bulundu": True})
    r = chat.ask("Geçen hafta Ahmet ne anlattı?", generate=llm, people=[], now=NOW)
    assert r["sources"] and r["sources"][0]["speaker"] == "Ahmet Yılmaz"


def test_made_up_words_without_person_or_date_find_nothing(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": ["helikopter"]})
    assert not chat.ask("helikopter?", generate=llm, people=[], now=NOW)["found"]


# ---------------------------------------------------------------- small talk, vague questions, empty days
@pytest.mark.parametrize("q,start", [("Selam", "Merhaba"), ("selam, nasılsın?", "İyiyim"), ("Teşekkürler!", "Rica"),
                                     ("sağ ol", "Rica"), ("tamam", "Tamam")])
def test_small_talk_needs_no_model(q, start):
    llm = FakeLLM({})
    r = chat.ask(q, generate=llm, people=[], now=NOW)
    assert r["answer"].startswith(start) and llm.calls == []


def test_small_talk_does_not_swallow_questions():
    assert chat.small_talk("selam, dün ne konuştuk?", "tr") is None
    assert chat.small_talk("teşekkürler, kararlar neydi", "tr") is None


def test_vague_question_asks_back(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": ["toplantı"]})
    r = chat.ask("bir şey sorcam", generate=llm, people=[], now=NOW)
    assert r["answer"].startswith("Hangi toplantıyı") and len(llm.calls) == 1


def test_day_without_recordings_names_the_nearest(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "ozet", "kisiler": [], "anahtar": []})
    r = chat.ask("3 ocakta ne konuşuldu", generate=llm, people=[], now=NOW)
    assert "kayıt yok" in r["answer"] and "En yakın kayıtlar" in r["answer"] and len(llm.calls) == 1


def test_old_dates_are_not_carried_to_an_unrelated_question(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": []})
    hist = [{"q": "dün ne konuştuk", "range": "x", "range_ts": [0, 1]}]
    r = chat.ask("hmm", hist, generate=llm, people=[], now=NOW)
    assert r["answer"].startswith("Hangi toplantıyı")


def test_month_names_are_not_search_words():
    assert chat.clean_words(["kasım", "bütçe"], []) == ["bütçe"]


def test_meeting_question_called_off_topic_is_still_searched(data):
    llm = FakeLLM({"niyet": "kapsam_disi", "tur": "genel", "kisiler": [], "anahtar": []},
                  {"cevap": "Ödeme ekranı yavaş.", "kaynaklar": [1], "bulundu": True})
    r = chat.ask("Ödeme ekranı neden yavaş?", generate=llm, people=[], now=NOW)
    assert r["intent"]["niyet"] == "kayit" and r["sources"] and len(llm.calls) == 2


def test_one_common_word_does_not_make_a_general_question_a_meeting_question(data):
    llm = FakeLLM({"niyet": "kapsam_disi", "tur": "genel", "kisiler": [], "anahtar": []})
    r = chat.ask("Python ekranı nasıl temizlenir?", generate=llm, people=[], now=NOW)
    assert r["answer"].startswith("Bu konuda yardımcı olamıyorum")
