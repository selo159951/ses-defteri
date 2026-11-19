"""Search by meaning: index, update, delete, hybrid ranking. A fake embedder stands in for the model
(words of the same concept share a dimension), and everything lives in a temporary home folder."""
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))

from backend import semantic, store  # noqa: E402
from search_meetings import MEETINGS, SPEAKERS  # noqa: E402

CONCEPTS = [("fiyat", "zam", "ücret", "yükselt", "artır", "artış", "pahal"),
            ("hata", "kilitlen", "çök"), ("yayın", "sürüm", "yayınla"),
            ("kargo", "teslimat", "paket"), ("iade", "geri ödeme"), ("maaş", "bütçe", "kadro")]


class FakeEmbedder:
    def __init__(self):
        self.calls = 0  # number of texts embedded

    def embed(self, texts, batch=16, should_stop=None):
        self.calls += len(texts)
        out = np.zeros((len(texts), 384), dtype=np.float32)
        for i, t in enumerate(texts):
            t = semantic.fold(t)
            for w in semantic._WORD.findall(t):
                for c, group in enumerate(CONCEPTS):
                    if any(w.startswith(semantic.fold(g)) for g in group):
                        out[i, c] += 1.0
                out[i, 50 + int(hashlib.md5(w.encode()).hexdigest(), 16) % 300] += 0.15
            out[i] /= np.linalg.norm(out[i]) or 1
        return out


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(semantic, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(semantic, "FLOOR", 0.0)  # the fake's scores are not e5's; the floor is for the real model
    semantic._cache.clear()
    semantic._skipped.clear()
    fake = FakeEmbedder()
    semantic.set_embedder(fake)
    yield fake
    semantic.set_embedder(None)
    semantic._cache.clear()


def make_job(name, lines, status="done"):
    jid = store.create_job(name)
    segs = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 8, "speaker": spk, "text_edited": t,
             "text_original": t, "words": []} for i, (spk, t) in enumerate(lines)]
    store.update_job(jid, status=status, segments=segs, speakers=dict(SPEAKERS), language="tr")
    return jid


def fixture_jobs():
    return [make_job(name, lines) for name, lines in MEETINGS]


def test_windows_group_lines_and_skip_empty():
    segs = [{"id": i, "start": float(i), "text_edited": t} for i, t in
            enumerate(["kısa", "", "başka bir şey", "x" * 250, "son"])]
    w = semantic.make_windows(segs)
    assert [x["segs"] for x in w] == [[0, 2, 3], [4]]  # the empty line is skipped, a long line closes a passage
    assert w[0]["start"] == 0.0 and w[0]["text"].startswith("kısa başka")


def test_index_build_then_fresh_then_incremental(home):
    jid = make_job("Fiyat", MEETINGS[0][1])
    assert semantic.index_job(jid) == "built"
    assert (store.job_path(jid) / "embeddings.npy").is_file() and (store.job_path(jid) / "embeddings.json").is_file()
    n = home.calls
    assert semantic.index_job(jid) == "fresh" and home.calls == n  # nothing changes, nothing is embedded
    store.save_edits(jid, {7: "Yıllık pakette indirim oranını yüzde otuzda tutarız."})
    assert semantic.index_job(jid) == "updated"
    assert 0 < home.calls - n <= 2  # only the passage that holds the edited line is embedded again


def test_touch_without_text_change_only_refreshes_stamp(home):
    jid = make_job("Fiyat", MEETINGS[0][1])
    semantic.index_job(jid)
    n = home.calls
    store.rename_job(jid, "Yeni ad")
    assert not semantic.is_fresh(jid)
    assert semantic.index_job(jid) == "fresh" and home.calls == n
    assert semantic.is_fresh(jid)


def test_unfinished_jobs_are_not_indexed():
    jid = make_job("Yarım", MEETINGS[0][1], status="running")
    assert semantic.index_job(jid) == "skipped"
    assert semantic.work_once() == 0 and semantic.coverage() == {"indexed": 0, "total": 1}


def test_search_finds_meaning_without_the_words():
    fixture_jobs()
    for j in store.jobs_dir().iterdir():
        semantic.index_job(j.name)
    r = semantic.search("fiyat artışı ne zaman konuşulmuştu")
    assert r["ready"] and r["indexed"] == r["total"] == 4
    top = r["results"][0]
    assert top["filename"] == "Fiyat toplantısı"
    assert "zam" in top["text"] or "ücret" in top["text"]  # not the words of the question
    assert top["start"] >= 0 and top["speaker"] in SPEAKERS.values() and top["seg"] in (0, 1, 2, 3, 4, 5, 6, 7)
    assert all(x["filename"] != "Mobil uygulama planı" for x in r["results"])  # other topics stay out


def test_hybrid_exact_phrase_comes_first(monkeypatch):
    a = make_job("A", [(0, "Zam konusunda herkes hemfikir.")])
    b = make_job("B", [(1, "Fiyat politikası değişecek, tarifeyi sonra konuşuruz.")])
    for j in (a, b):
        semantic.index_job(j)
    # the question appears literally only in A; B is the closer match by meaning
    r = semantic.search("zam konusunda")
    assert r["results"][0]["job_id"] == a and r["results"][0]["exact"]
    r = semantic.search("fiyat zam")
    assert {x["job_id"] for x in r["results"]} == {a, b}


def test_rename_edit_and_delete_are_followed():
    jid = make_job("Eski ad", MEETINGS[0][1])
    semantic.index_job(jid)
    assert semantic.search("zam")["results"][0]["filename"] == "Eski ad"
    store.rename_job(jid, "Yeni ad")
    assert semantic.search("zam")["results"][0]["filename"] == "Yeni ad"  # the name is read when results are made
    store.delete_job(jid)
    r = semantic.search("zam")
    assert r["results"] == [] and r["total"] == 0


def test_stale_index_is_rebuilt_in_the_background_pass(home):
    ids = fixture_jobs()
    assert sorted(semantic.stale_jobs()) == sorted(ids)
    assert semantic.work_once() == 4
    assert semantic.stale_jobs() == [] and semantic.coverage()["indexed"] == 4
    time.sleep(0.02)
    store.save_edits(ids[0], {0: "Başka bir şey söyledim."})
    assert semantic.stale_jobs() == [ids[0]]
    n = home.calls
    assert semantic.work_once() == 1 and home.calls - n >= 1


def test_worker_stays_out_of_the_way_of_transcription(monkeypatch):
    fixture_jobs()
    monkeypatch.setattr(semantic, "busy", lambda: True)
    assert semantic.work_once() == 0 and semantic.coverage()["indexed"] == 0

    class Stopper(FakeEmbedder):  # a transcription starts in the middle of a recording: it is dropped, not half written
        def embed(self, texts, batch=16, should_stop=None):
            if should_stop and should_stop():
                raise InterruptedError
            return super().embed(texts, batch, should_stop)

    monkeypatch.setattr(semantic, "busy", lambda: False)
    jid = store.jobs_dir().iterdir().__next__().name
    monkeypatch.setattr(semantic, "busy", lambda: True)
    with pytest.raises(InterruptedError):
        semantic.index_job(jid, Stopper(), should_stop=semantic.busy)
    assert not (store.job_path(jid) / "embeddings.json").exists()


def test_other_model_means_rebuild(monkeypatch):
    jid = make_job("Fiyat", MEETINGS[0][1])
    semantic.index_job(jid)
    monkeypatch.setitem(semantic.MODEL, "name", "baska-model")
    assert semantic.read_meta(jid) is None and not semantic.is_fresh(jid)
    assert semantic.index_job(jid) == "built"


def test_search_without_model_reports_not_ready(monkeypatch):
    semantic.set_embedder(None)
    monkeypatch.setenv("SESDEFTERI_MODEL_DIR", str(Path(os.environ["SESDEFTERI_HOME"]) / "nomodels"))
    r = semantic.search("fiyat")
    assert r["ready"] is False and r["results"] == []
    assert not semantic.is_downloaded() and semantic.status()["downloaded"] is False


def test_many_recordings_stay_fast():
    lines = MEETINGS[0][1] * 4
    ids = [make_job(f"Kayıt {i}", lines) for i in range(60)]
    for j in ids:
        semantic.index_job(j)
    semantic.search("zam")  # loads the matrices into memory
    t0 = time.time()
    r = semantic.search("fiyat artışı")
    assert time.time() - t0 < 2.0 and r["total"] == 60
