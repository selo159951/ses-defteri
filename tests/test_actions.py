"""Assistant actions: "Ece'yi kişilere ekle" and friends are read from the words themselves (or by the
model) and answered with an action card instead of an answer; the backend finds the speakers, groups
their voices and adds them to one person. Synthetic data only; the model is a fake, voice prints too."""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import actions, chat, people, store  # noqa: E402

NOW = dt.datetime(2026, 11, 19, 15, 0)  # a Thursday
MON = dt.date(2026, 11, 16)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))


def ts(d: dt.date, h=10) -> float:
    return dt.datetime.combine(d, dt.time(h)).timestamp()


def make_job(name, when, lines, speakers, status="done"):
    jid = store.create_job(name)
    segs = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 9, "speaker": s, "text_original": t, "text_edited": t}
            for i, (s, t) in enumerate(lines)]
    store.update_job(jid, status=status, created=when, duration=len(lines) * 10.0, speakers=speakers, segments=segs)
    return jid


@pytest.fixture
def data():
    """Three finished recordings where a speaker is called Ece (and one that is still running)."""
    a = make_job("Butce Gorusmesi.mp3", ts(MON - dt.timedelta(days=5)), [(0, "Merhaba."), (1, "Ece olarak tanıtayım.")],
                 {"0": "Ayşe", "1": "Ece"})
    b = make_job("Toplanti B.mp3", ts(MON), [(0, "Selam."), (1, "Ben Ece.")], {"0": "Ayşe", "1": "ECE Hanım"})
    c = make_job("Toplanti C.mp3", ts(MON + dt.timedelta(days=1)), [(0, "iyi gunler"), (1, "Ece benim")],
                 {"0": "Ayşe", "1": "Ece"})
    make_job("Yarim.mp3", ts(MON), [(0, "Bu is daha bitmedi")], {"0": "Ece"}, status="running")
    return {"a": a, "b": b, "c": c}


class FakeLLM:
    def __init__(self, intent, answer=None):
        self.intent, self.answer, self.calls = intent, answer, []

    def __call__(self, prompt, schema=None, system=None, **kw):
        self.calls.append({"prompt": prompt, "schema": schema, "system": system})
        if schema is chat.INTENT_SCHEMA:
            return dict(self.intent)
        if schema is chat.ANSWER_SCHEMA:
            return dict(self.answer)
        return ""


# ---------------------------------------------------------------- reading the action from the words
@pytest.mark.parametrize("q,eylem,ad,kayit", [
    ("Ece'yi kişilere ekle", "kisi_ekle", "Ece", ""),
    ("Ahmet'i kişiler sayfasına ekle", "kisi_ekle", "Ahmet", ""),
    ("add Ece to people", "kisi_ekle", "Ece", ""),
    ("add Ece to contacts", "kisi_ekle", "Ece", ""),
    ("son kaydı aç", "kayit_ac", "", "son"),
    ("Dünkü toplantıyı aç", "kayit_ac", "", "Dünkü"),
    ("bütçe toplantısını aç", "kayit_ac", "", "bütçe"),
    ("open the last recording", "kayit_ac", "", "last"),
    ("open the latest meeting", "kayit_ac", "", "latest"),
])
def test_detect_action(q, eylem, ad, kayit):
    a = chat.detect_action(q)
    assert a is not None, q
    assert a["eylem"] == eylem and a["ad"] == ad and a["kayit"] == kayit


@pytest.mark.parametrize("q", ["Ahmet ne dedi", "geçen hafta hangi kararlar alındı", "Ece kimdir",
                               "Kişiler sayfası nasıl çalışır", "toplantı hakkında konuşalım"])
def test_questions_without_an_action(q):
    assert chat.detect_action(q) is None


def test_ask_returns_the_action_without_calling_the_model(data):
    llm = FakeLLM({})
    r = chat.ask("Ece'yi kişilere ekle", generate=llm, people=[], now=NOW)
    assert llm.calls == []  # the words were enough: no model run at all
    assert r["found"] and r["sources"] == []
    assert r["action"] == {"eylem": "kisi_ekle", "ad": "Ece", "kayit": "", "konusmaci": 0}
    assert "Ece" in r["answer"]


def test_ask_returns_the_action_the_model_read(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": [],
                   "eylem": "konusmaci_adi", "eylem_ad": "Ahmet", "eylem_kayit": "son kayıt", "eylem_konusmaci": 2})
    r = chat.ask("son kayıttaki konuşmacı 2 Ahmet olsun", generate=llm, people=[], now=NOW)
    assert len(llm.calls) == 1  # the question was read, but there was no answer step
    assert r["action"]["eylem"] == "konusmaci_adi" and r["action"]["konusmaci"] == 2
    assert r["action"]["ad"] == "Ahmet" and r["action"]["kayit"] == "son kayıt"


def test_action_without_a_name_is_ignored(data):
    llm = FakeLLM({"niyet": "kayit", "tur": "genel", "kisiler": [], "anahtar": [],
                   "eylem": "kisi_ekle", "eylem_ad": "", "eylem_kayit": "", "eylem_konusmaci": 0})
    r = chat.ask("kişilere birini ekle", generate=llm, people=[], now=NOW)
    assert "action" not in r  # a name cannot be guessed: the question is answered the normal way


# ---------------------------------------------------------------- finding a recording
def test_find_recording_last(data):
    r = actions.find_recording("son kayıt", NOW)
    assert [x["id"] for x in r] == [data["c"]]  # the newest finished one, not the running job


def test_find_recording_by_date_and_title(data):
    assert [x["id"] for x in actions.find_recording("16 kasım toplantısı", NOW)] == [data["b"]]
    assert [x["id"] for x in actions.find_recording("bütçe görüşmesi", NOW)] == [data["a"]]
    assert actions.find_recording("helikopter toplantısı", NOW) == []


def test_find_recording_when_nothing_is_done():
    make_job("Yarim.mp3", ts(MON), [(0, "x")], {"0": "Ayşe"}, status="running")
    assert actions.find_recording("son", NOW) == []


# ---------------------------------------------------------------- grouping the voices of a name
def _person_with_voice(name, vector):
    p = people.create_person(name)
    with people._lock:
        raw = people._read(p["id"])
        raw["embedding"] = [float(x) for x in vector]
        people._write(raw)
    return p


def test_same_name_groups_into_one_person(data, monkeypatch):
    prints = {data["a"]: np.array([1.0, 0.0, 0.0]), data["b"]: np.array([0.99, 0.05, 0.0]),
              data["c"]: np.array([0.0, 1.0, 0.0])}
    monkeypatch.setattr(actions, "speaker_print", lambda jid, spk: prints.get(jid))
    _person_with_voice("Ece", np.array([1.0, 0.0, 0.0]))
    r = actions.find_speaker_groups("ece")  # case and Turkish letters do not matter
    assert r["name"] == "ece" and r["skipped"] == 0
    assert len(r["groups"]) == 2  # A and B are alike; C is another voice
    first, second = r["groups"][0], r["groups"][1]
    assert {it["job_id"] for it in first["items"]} == {data["a"], data["b"]}  # "ECE Hanım" counts as Ece
    assert [it["job_id"] for it in second["items"]] == [data["c"]]
    assert first["person"]["name"] == "Ece" and first["person"]["score"] >= people.SUGGEST
    assert second["person"] is None  # the second voice is nobody we know
    it = first["items"][0]
    assert set(it) == {"job_id", "title", "speaker", "seconds", "sample_start"}
    assert it["speaker"] == 1 and it["sample_start"] == 10.0


def test_too_little_speech_is_skipped(data, monkeypatch):
    monkeypatch.setattr(actions, "speaker_print", lambda jid, spk: None)
    r = actions.find_speaker_groups("Ece")
    assert r["groups"] == [] and r["skipped"] == 3


def test_unknown_name_finds_nothing(data, monkeypatch):
    monkeypatch.setattr(actions, "speaker_print", lambda jid, spk: np.array([1.0, 0.0, 0.0]))
    r = actions.find_speaker_groups("Mehmet")
    assert r["groups"] == [] and r["skipped"] == 0


# ---------------------------------------------------------------- adding and naming
def test_add_group_puts_every_item_into_one_person(monkeypatch):
    calls = []

    def fake_add(job_id, speaker, pid, name):
        calls.append({"job_id": job_id, "speaker": speaker, "pid": pid, "name": name})
        return {"id": "p1", "name": name}

    monkeypatch.setattr(people, "add_sample_from_job", fake_add)
    person = actions.add_group("Ece", [{"job_id": "aaa", "speaker": 1}, {"job_id": "bbb", "speaker": 2}])
    assert person == {"id": "p1", "name": "Ece"}
    assert [c["pid"] for c in calls] == [None, "p1"]  # the first item creates the person, the rest join it
    assert all(c["name"] == "Ece" for c in calls)


def test_add_group_with_an_existing_person(monkeypatch):
    calls = []

    def fake_add(job_id, speaker, pid, name):
        calls.append(pid)
        return {"id": pid, "name": name}

    monkeypatch.setattr(people, "add_sample_from_job", fake_add)
    actions.add_group("Ece", [{"job_id": "aaa", "speaker": 1}], "px")
    assert calls == ["px"]


def test_name_speaker(data):
    actions.name_speaker(data["a"], 1, "Ece Yılmaz")
    assert store.read_transcript(data["a"])["speakers"]["1"] == "Ece Yılmaz"
