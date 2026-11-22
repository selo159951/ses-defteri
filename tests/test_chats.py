"""Saved assistant conversations: create/list/get/rename/delete, auto-titles that never override a
manual rename, a corrupt file that means "no chats" instead of a crash, and the limits.
The language model is a fake. Synthetic data only."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import bridge, chat, chats, pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))


class Clock:
    """time.time() that always moves forward, so the list order is deterministic."""

    def __init__(self):
        self.t = 1_700_000_000.0

    def time(self):
        self.t += 1.0
        return self.t


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(chats.time, "time", c.time)
    return c


def chats_file() -> Path:
    return chats._path()


# ---------------------------------------------------------------- storage
def test_save_creates_list_get():
    a = chats.save(None, [{"role": "user", "text": "selam"}], [], "Dünkü toplantıda kararlar")
    b = chats.save(None, [{"role": "user", "text": "q"}], [], "Bütçe toplantısı")
    assert a["id"] != b["id"] and len(a["id"]) == 8
    assert a["title"] == "Dünkü toplantıda kararlar"
    lst = chats.list_chats()
    assert [c["id"] for c in lst] == [b["id"], a["id"]]  # newest first
    assert lst[0]["count"] == 1 and "msgs" not in lst[0]
    full = chats.get(b["id"])
    assert full["msgs"] == [{"role": "user", "text": "q"}] and full["history"] == []
    assert full["auto_title"] is True and full["created"] <= full["updated"]
    assert chats.get("nope") is None


def test_save_updates_existing_chat():
    s = chats.save(None, [{"role": "user", "text": "q"}], [], "Ahmet ne dedi")
    s2 = chats.save(s["id"], [{"role": "user", "text": "q"}, {"role": "assistant", "text": "a"}],
                    [{"q": "Ahmet ne dedi"}], "unimportant")
    assert s2["id"] == s["id"] and s2["count"] == 2
    full = chats.get(s["id"])
    assert len(full["msgs"]) == 2 and full["history"] == [{"q": "Ahmet ne dedi"}]
    assert full["title"] == "Ahmet ne dedi"  # an existing chat keeps its name
    assert full["updated"] > full["created"]


def test_save_unknown_id_creates_new():
    s = chats.save("deadbeef", [{"role": "user", "text": "q"}], [], "Yeni konu")
    assert s["id"] != "deadbeef" and s["title"] == "Yeni konu"


def test_rename():
    s = chats.save(None, [], [], "eski")
    out = chats.rename(s["id"], "  Bütçe planlaması  ")
    assert out["title"] == "Bütçe planlaması"
    assert chats.get(s["id"])["auto_title"] is False
    assert chats.rename(s["id"], "   ")["title"] == "Bütçe planlaması"  # empty name changes nothing
    assert chats.rename(s["id"], "x" * 200)["title"] == "x" * chats.NAME_MAX
    assert chats.rename("nope", "n") is None


def test_delete():
    s = chats.save(None, [], [], "silinecek")
    assert chats.delete(s["id"]) is True
    assert chats.get(s["id"]) is None and chats.list_chats() == []
    assert chats.delete(s["id"]) is False


def test_auto_title_does_not_override_manual_rename():
    s = chats.save(None, [], [], "Geçen haftaki bütçe")
    assert chats.set_auto_title(s["id"], "Bütçe görüşmesi")["title"] == "Bütçe görüşmesi"
    assert chats.set_auto_title(s["id"], "  ")["title"] == "Bütçe görüşmesi"  # empty changes nothing
    chats.rename(s["id"], "Benim adım")
    assert chats.set_auto_title(s["id"], "modelin adı") is None
    assert chats.get(s["id"])["title"] == "Benim adım"
    assert chats.set_auto_title("nope", "x") is None


def test_corrupt_or_missing_file():
    assert chats.list_chats() == []  # no file yet
    chats_file().write_text("{börek json", "utf-8")
    assert chats.list_chats() == []
    s = chats.save(None, [], [], "kurtarma")  # a corrupt file is overwritten, not fatal
    assert chats.get(s["id"])["title"] == "kurtarma"
    chats_file().write_text(json.dumps([{"title": "no id here"}]), "utf-8")  # entries without an id are dropped
    assert chats.list_chats() == []


def test_limits():
    for i in range(chats.MAX_CHATS + 3):
        chats.save(None, [], [], f"sohbet {i}")
    lst = chats.list_chats()
    assert len(lst) == chats.MAX_CHATS
    assert lst[-1]["title"] == "sohbet 3"  # the three oldest-updated ones are dropped
    s = chats.save(None, [], [], "400 mesaj")
    msgs = [{"role": "user", "text": f"m{i}"} for i in range(500)]
    chats.save(s["id"], msgs, [], "")
    assert len(chats.get(s["id"])["msgs"]) == chats.MAX_MSGS
    assert chats.get(s["id"])["msgs"][0]["text"] == "m100"  # the newest are kept


# ---------------------------------------------------------------- fallback title
def test_fallback_title():
    assert chats.fallback_title("Dünkü toplantıda hangi kararlar alındı acaba?") == "Dünkü toplantıda hangi kararlar alındı acaba"
    assert chats.fallback_title("bir iki üç dört beş altı yedi sekiz") == "bir iki üç dört beş altı"
    assert chats.fallback_title("x" * 100) == "x" * chats.TITLE_MAX
    assert chats.fallback_title("  kelime...  ") == "kelime"
    assert chats.fallback_title("") == "Yeni sohbet"
    assert chats.fallback_title("   ") == "Yeni sohbet"


# ---------------------------------------------------------------- model titles
def test_make_title_good_output():
    gen = lambda prompt, **kw: "**Fiyat artışı görüşmesi**.\n"
    assert chat.make_title("Fiyatlar neden arttı?", "Cevap…", "tr", generate=gen) == "Fiyat artışı görüşmesi"


def test_make_title_quoted_and_dotted_output():
    gen = lambda prompt, **kw: '"Bütçe toplantısı."'
    assert chat.make_title("Bütçe?", "a", "tr", generate=gen) == "Bütçe toplantısı"


def test_make_title_long_output_is_cut():
    gen = lambda prompt, **kw: "çok " * 40
    assert len(chat.make_title("q", "a", "tr", generate=gen)) <= chats.TITLE_MAX


def test_make_title_exception_falls_back():
    def boom(prompt, **kw):
        raise RuntimeError("model yok")

    assert chat.make_title("Ahmet fiyat hakkında ne dedi?", "a", "tr", generate=boom) \
        == chats.fallback_title("Ahmet fiyat hakkında ne dedi?")


def test_make_title_empty_output_falls_back():
    assert chat.make_title("Ahmet ne dedi?", "a", "tr", generate=lambda p, **kw: "   ") \
        == chats.fallback_title("Ahmet ne dedi?")


def test_make_title_small_talk_never_calls_the_model():
    calls = []

    def gen(prompt, **kw):
        calls.append(prompt)
        return "Merhaba"

    assert chat.make_title("merhaba", "Merhaba! ...", "tr", generate=gen) == chats.fallback_title("merhaba")
    assert calls == []


# ---------------------------------------------------------------- the bridge
@pytest.fixture
def api():
    return bridge.Api(window_getter=lambda: None)


def test_bridge_chat_crud(api):
    assert api.chat_list() == []
    assert api.chat_get("nope") == {"error": "not_found"}
    s = api.chat_save(None, [{"role": "user", "text": "q"}], [], "Bütçe toplantısı")
    assert api.chat_list()[0]["id"] == s["id"]
    assert api.chat_get(s["id"])["title"] == "Bütçe toplantısı"
    assert api.chat_save(s["id"], [{"role": "user", "text": "q2"}], [], "")["count"] == 1
    assert api.chat_rename(s["id"], "  Yeni ad  ")["title"] == "Yeni ad"
    assert api.chat_delete(s["id"]) == {"ok": True}
    assert api.chat_list() == []


def test_bridge_chat_bad_args_never_raise(api):
    assert "error" in api.chat_save(None, "msgs değil", [], "x")
    assert "error" in api.chat_save(None, [], 5, "x")
    assert "error" in api.chat_get(123)
    assert "error" in api.chat_rename(None, "x")
    assert "error" in api.chat_delete(None)
    assert "error" in api.chat_autotitle(None, "q", "a")


def test_bridge_autotitle(api, monkeypatch):
    s = api.chat_save(None, [{"role": "user", "text": "q"}], [], "Fiyatlar neden arttı?")
    monkeypatch.setattr("backend.analysis.llm_ready", lambda: False)
    idle = pipeline._current["id"]
    try:
        pipeline._current["id"] = ""  # nothing is being transcribed
        out = api.chat_autotitle(s["id"], "Fiyatlar neden arttı?", "…", "tr")
        assert out == {"title": chats.fallback_title("Fiyatlar neden arttı?")}  # no model: the fallback stays

        monkeypatch.setattr("backend.analysis.llm_ready", lambda: True)
        monkeypatch.setattr(chat, "make_title", lambda q, a, lang, generate=None: "Fiyat artışı görüşmesi")
        out = api.chat_autotitle(s["id"], "Fiyatlar neden arttı?", "…", "tr")
        assert out == {"title": "Fiyat artışı görüşmesi"}
        assert chats.get(s["id"])["title"] == "Fiyat artışı görüşmesi"

        pipeline._current["id"] = "busyjob"  # a transcription is running: the model is not bothered
        out = api.chat_autotitle(s["id"], "Bütçe ne durumda?", "…", "tr")
        assert out == {"title": chats.fallback_title("Bütçe ne durumda?")}
    finally:
        pipeline._current["id"] = idle

    api.chat_rename(s["id"], "Benim adım")
    assert api.chat_autotitle(s["id"], "başka soru", "a", "tr") == {"title": "Benim adım"}
    assert api.chat_autotitle("nope", "q", "a", "tr") == {"error": "not_found"}
