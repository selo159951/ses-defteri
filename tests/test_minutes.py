"""Meeting minutes: built-in layout, the user's Word template with placeholders, logo and settings. Synthetic data only."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document  # noqa: E402

from backend import asr, minutes  # noqa: E402

def _png() -> bytes:
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = (b"\x00" + b"\xff\x00\x00" * 2) * 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))


def job():
    segs = [
        {"id": 0, "start": 0.0, "end": 30.0, "speaker": 0, "text_original": "Merhaba", "text_edited": "Merhaba, başlayalım."},
        {"id": 1, "start": 30.0, "end": 40.0, "speaker": 1, "text_original": "Tamam", "text_edited": "Tamam."},
        {"id": 2, "start": 40.0, "end": 50.0, "speaker": 0, "text_original": "x", "text_edited": "Sürüm cuma çıkar."},
    ]
    return {"id": "j1", "filename": "Haftalik toplanti.mp3", "created": 1763712000.0, "duration": 3725,
            "speakers": {"0": "Ayşe", "1": "Speaker 2"}, "segments": segs}


def analysis():
    return {"summary": "Sürüm tarihi konuşuldu.",
            "chapters": [{"start": 0, "end": 40, "title": "Açılış", "summary": "Gündem"}],
            "decisions": [{"text": "Sürüm cuma çıkacak"}, {"text": "Test haftası eklenecek"}],
            "tasks": [{"owner": 0, "task": "Notları gönder", "due": "Pazartesi"}, {"owner": 1, "task": "Testleri yaz"}],
            "open_questions": [{"asker": 1, "text": "Bütçe yeter mi?"}],
            "stats": {"speakers": [{"id": 0, "share": 0.8}, {"id": 1, "share": 0.2}]}}


def text_of(data: bytes) -> str:
    d = Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    for s in d.sections:
        parts += [p.text for p in s.header.paragraphs] + [p.text for p in s.footer.paragraphs]
    return "\n".join(parts)


# ---------------------------------------------------------------- placeholders
@pytest.mark.parametrize("raw,key", [("özet", "ozet"), ("OZET", "ozet"), ("açık_sorular", "aciksorular"),
                                     ("Açık sorular", "aciksorular"), ("görev.kim", "gorev.kim"), (" süre ", "sure")])
def test_key_of(raw, key):
    assert minutes.key_of(raw) == key


def test_context_values():
    c = minutes.context(job(), analysis(), "tr", "ACME")
    assert c["sure"] == "1 sa 2 dk" and c["kayit"] == "Haftalik toplanti" and c["sirket"] == "ACME"
    assert c["katilimcilar"] == "Ayşe, Konuşmacı 2"
    assert c["katilimcilistesi"][0] == "Ayşe (%80 konuşma payı)"
    assert c["gorevler"][0] == {"kim": "Ayşe", "ne": "Notları gönder", "tarih": "Pazartesi"}
    assert c["aciksorular"] == ["Konuşmacı 2: Bütçe yeter mi?"]
    assert c["metin"][2].endswith("Ayşe: Sürüm cuma çıkar.")


def test_participants_without_analysis_use_talk_time():
    c = minutes.context(job(), None, "en")
    assert c["katilimcilar"] == "Ayşe, Speaker 2"
    assert c["katilimcilistesi"][0] == "Ayşe (80% of the talk)"


# ---------------------------------------------------------------- built-in
def test_builtin_has_everything_in_order():
    asr.set_setting("company_name", "ACME Yazılım")
    asr.set_setting("minutes_sections", ["participants", "decisions", "tasks", "summary"])
    txt = text_of(minutes.build(job(), analysis(), "tr"))
    assert "Toplantı Tutanağı" in txt and "ACME Yazılım" in txt and "1 sa 2 dk" in txt
    assert "Ayşe | Notları gönder | Pazartesi" in txt and "Konuşmacı 2 | Testleri yaz | —" in txt
    assert txt.index("Alınan kararlar") < txt.index("Görevler") < txt.index("Özet")
    assert "Açık sorular" not in txt  # not chosen
    assert "Ses Defteri ile hazırlandı" in txt


def test_builtin_without_analysis_says_so_and_keeps_basics():
    asr.set_setting("minutes_sections", ["participants", "summary", "transcript"])
    txt = text_of(minutes.build(job(), None, "tr"))
    assert "analizi yapılmadı" in txt and "Katılımcılar" in txt and "Konuşma metni" in txt
    assert "Özet" not in txt
    txt = text_of(minutes.build(job(), None, "tr", note_missing=False))
    assert "analizi yapılmadı" not in txt


def test_builtin_with_logo_and_color():
    src = Path(minutes.store.data_dir()) / "l.png"
    src.write_bytes(PNG)
    minutes.set_logo(str(src))
    asr.set_setting("company_color", "#ff0000")
    d = Document(io.BytesIO(minutes.build(job(), analysis(), "tr")))
    assert d.sections[0].header.part.package  # header exists
    assert any(r.element.xpath(".//pic:pic") for p in d.sections[0].header.paragraphs for r in p.runs)
    assert str(d.paragraphs[0].runs[0].font.color.rgb) == "FF0000"


def test_settings_are_cleaned():
    asr.set_setting("company_color", "red; drop")
    asr.set_setting("minutes_sections", ["tasks", "evil", "tasks", "summary"])
    cfg = minutes.config()
    assert cfg["company_color"] == minutes.DEFAULT_COLOR and cfg["sections"] == ["tasks", "summary"]


@pytest.mark.parametrize("name,data", [("a.gif", PNG), ("a.png", b"not a picture"), ("a.png", PNG + b"0" * (3 << 20)), ("a.png", PNG[:20])])
def test_bad_logo_rejected(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    with pytest.raises(ValueError):
        minutes.set_logo(str(p))


# ---------------------------------------------------------------- user template
def template(build) -> Path:
    d = Document()
    build(d)
    p = Path(minutes.store.data_dir()) / "src.docx"
    d.save(p)
    minutes.set_template(str(p))
    return p


def test_template_split_runs_and_ascii_names():
    def b(d):
        p = d.add_paragraph()
        for piece in ("Tarih: {ta", "rih} – ", "{OZET}", " / {sure}"):
            p.add_run(piece).bold = True
        d.add_paragraph("Bilinmeyen {foo} kalır")
    template(b)
    txt = text_of(minutes.build(job(), analysis(), "tr"))
    assert "Tarih: 21.11.2025 – Sürüm tarihi konuşuldu. / 1 sa 2 dk" in txt.replace("21.11.2025", "21.11.2025")
    assert "Bilinmeyen {foo} kalır" in txt


def test_template_lists_and_task_rows_and_header():
    def b(d):
        d.sections[0].header.paragraphs[0].text = "{şirket} · {kayıt}"
        d.add_paragraph("Kararlar:")
        d.add_paragraph("{kararlar}", style="List Bullet")
        t = d.add_table(rows=2, cols=3)
        for c, x in zip(t.rows[0].cells, ("Kim", "Ne", "Tarih")):
            c.text = x
        for c, x in zip(t.rows[1].cells, ("{görev.kim}", "{görev.ne}", "{görev.tarih}")):
            c.text = x
        d.add_paragraph("Sorular: {açık_sorular}")
    asr.set_setting("company_name", "ACME")
    template(b)
    out = minutes.build(job(), analysis(), "tr")
    d = Document(io.BytesIO(out))
    assert d.sections[0].header.paragraphs[0].text == "ACME · Haftalik toplanti"
    bullets = [p.text for p in d.paragraphs if p.style.name == "List Bullet"]
    assert bullets == ["Sürüm cuma çıkacak", "Test haftası eklenecek"]
    rows = [[c.text for c in r.cells] for r in d.tables[0].rows]
    assert rows == [["Kim", "Ne", "Tarih"], ["Ayşe", "Notları gönder", "Pazartesi"], ["Konuşmacı 2", "Testleri yaz", ""]]
    assert "Sorular: Konuşmacı 2: Bütçe yeter mi?" in text_of(out)


def test_template_empty_lists_say_none():
    def b(d):
        d.add_paragraph("{kararlar}")
    template(b)
    assert "Yok" in text_of(minutes.build(job(), None, "tr"))


def test_template_can_be_turned_off_and_removed():
    template(lambda d: d.add_paragraph("ŞABLON {tarih}"))
    assert "ŞABLON" in text_of(minutes.build(job(), analysis(), "tr"))
    assert "ŞABLON" not in text_of(minutes.build(job(), analysis(), "tr", use_template=False))
    minutes.remove_template()
    assert "Toplantı Tutanağı" in text_of(minutes.build(job(), analysis(), "tr"))


def test_bad_template_rejected(tmp_path):
    p = tmp_path / "x.docx"
    p.write_bytes(b"not a word file")
    with pytest.raises(ValueError):
        minutes.set_template(str(p))
    with pytest.raises(ValueError):
        minutes.set_template(str(tmp_path / "x.pdf"))


def test_sample_template_fills_cleanly():
    p = Path(minutes.store.data_dir()) / "ornek.docx"
    p.write_bytes(minutes.sample_template())
    minutes.set_template(str(p))
    txt = text_of(minutes.build(job(), analysis(), "tr"))
    for leftover in ("{özet}", "{kararlar}", "{görev.kim}", "{tarih}", "{logo}", "{şirket}"):
        assert leftover not in txt
    assert "Sürüm cuma çıkacak" in txt and "Notları gönder" in txt
