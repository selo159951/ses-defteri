"""Star, tags and bulk actions in the recordings list. Synthetic data only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import bridge, store  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


def make_job(name="toplanti.wav", tags=None, starred=False):
    jid = store.create_job(name)
    store.update_job(jid, status="done", starred=starred, tags=tags or [])
    return jid


# ---------------------------------------------------------------- store
def test_star_roundtrip_and_list_summary():
    a, b = make_job("a.wav"), make_job("b.wav")
    store.set_star(a, True)
    jobs = {j["id"]: j for j in store.list_jobs()}
    assert jobs[a]["starred"] is True and jobs[b]["starred"] is False
    store.set_star(a, False)
    assert {j["id"]: j for j in store.list_jobs()}[a]["starred"] is False


def test_tags_cleaned():
    assert store.clean_tags([" toplantı ", "", "toplantı", "x" * 60, None, 5]) == ["toplantı", "x" * 40, "5"]
    assert store.clean_tags("tek") == ["tek"]  # a bare string, not a list
    assert store.clean_tags([f"t{i}" for i in range(25)]) == [f"t{i}" for i in range(20)]  # at most 20
    assert store.clean_tags([]) == []


def test_set_tags_and_summary():
    jid = make_job(tags=["eski"])
    store.set_tags(jid, [" a ", "a", "b"])
    j = {x["id"]: x for x in store.list_jobs()}[jid]
    assert j["tags"] == ["a", "b"]


def test_list_tags_unique_and_sorted():
    make_job("a.wav", tags=["ıspanak", "elma"])
    make_job("b.wav", tags=["elma", "Armut"])
    assert store.list_tags() == ["Armut", "elma", "ıspanak"]  # forgiving i/ı order


def test_delete_jobs_removes_all_and_rejects_bad_ids():
    a, b, c = make_job("a.wav"), make_job("b.wav"), make_job("c.wav")
    assert store.delete_jobs([a, c]) == [a, c]
    assert [j["id"] for j in store.list_jobs()] == [b]
    with pytest.raises(ValueError):
        store.delete_jobs([b, "../evil"])  # a bad id raises ...
    assert [j["id"] for j in store.list_jobs()] == [b]  # ... before anything is deleted


# ---------------------------------------------------------------- bridge
class FakeWin:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create_file_dialog(self, kind, **kw):
        self.calls.append(kw)
        return self.answer


def test_bridge_star_tags_list_and_delete():
    api = bridge.Api(lambda: FakeWin(None))
    a, b = make_job("a.wav"), make_job("b.wav")
    assert api.set_job_star(a, True) == {"ok": True}
    assert api.set_job_tags(a, [" a ", "a", "b"]) == {"ok": True, "tags": ["a", "b"]}
    assert api.set_job_tags(b, ["rapor"]) == {"ok": True, "tags": ["rapor"]}
    assert api.list_tags() == ["a", "b", "rapor"]
    jobs = {j["id"]: j for j in api.list_jobs()}
    assert jobs[a]["starred"] is True and jobs[a]["tags"] == ["a", "b"]
    assert api.delete_jobs([a, b]) == {"ok": True, "deleted": 2}
    assert api.list_jobs() == []
    with pytest.raises(ValueError):
        api.delete_jobs(["no/such"])


def seg(i, a, b, spk, text):
    return {"id": i, "start": a, "end": b, "speaker": spk, "text_original": text, "text_edited": text}


def filled_job(name):
    jid = store.create_job(name)
    store.update_job(jid, status="done", speakers={"0": "Deniz"},
                     segments=[seg(0, 0.0, 2.0, 0, "Merhaba.")])
    return jid


def test_bridge_export_jobs_one_folder_and_same_name_twice(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    a = filled_job("toplanti.wav")
    b = filled_job("toplanti.wav")  # same name: the second file gets a number
    c = filled_job("diger.wav")
    win = FakeWin(str(out))
    api = bridge.Api(lambda: win)
    r = api.export_jobs([a, b, c], "docx", "tr")
    assert [Path(p).name for p in r["paths"]] == ["toplanti.docx", "toplanti (2).docx", "diger.docx"]
    for p in r["paths"]:
        assert Path(p).read_bytes()[:2] == b"PK"
    api.export_jobs([c], "docx", "tr")
    assert win.calls[1]["directory"] == str(out)  # the folder used last is remembered


def test_bridge_export_jobs_cancel_and_bad_format(tmp_path):
    api = bridge.Api(lambda: FakeWin(None))
    assert api.export_jobs([filled_job("a.wav")], "docx") == {"cancelled": True}
    assert api.export_jobs([filled_job("a.wav")], "exe") == {"error": "bad format"}
    with pytest.raises(ValueError):
        api.export_jobs([], "docx")
