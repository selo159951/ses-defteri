"""Meeting minutes ("tutanak") as a Word file.

Two ways, set on the Settings page:
- built in: company logo and name on top, date / time / length, participants, then the chosen sections in the chosen
  order (summary, chapters, decisions, a task table, open questions, optional full transcript), headings in the
  company colour;
- the user's own Word template (%APPDATA%\\SesDefteri\\templates\\tutanak.docx) with placeholders such as {tarih},
  {özet}, {kararlar} or a table row with {görev.kim} {görev.ne} {görev.tarih}: the template keeps its own layout,
  fonts and logo, the app only fills the placeholders (see assets/tutanak-ornek.docx for the full list).

Without a meeting analysis (or in the simple edition) the minutes still have the date, length, participants and
the transcript; summary, decisions and tasks need the analysis.
"""
from __future__ import annotations

import copy
import datetime
import io
import re
from pathlib import Path

from . import asr, export, store

SECTIONS = ("participants", "summary", "chapters", "decisions", "tasks", "questions", "transcript")
DEFAULT_SECTIONS = ["participants", "summary", "chapters", "decisions", "tasks", "questions"]
DEFAULT_COLOR = "#2563eb"
MAX_LOGO = 2 * 1024 * 1024
MAX_TEMPLATE = 20 * 1024 * 1024

LABELS = {
    "tr": {"title": "Toplantı Tutanağı", "date": "Tarih", "time": "Saat", "length": "Süre", "recording": "Kayıt",
           "participants": "Katılımcılar", "summary": "Özet", "chapters": "Gündem ve bölümler",
           "decisions": "Alınan kararlar", "tasks": "Görevler", "who": "Kim", "what": "Ne", "when": "Ne zaman",
           "questions": "Açık sorular", "transcript": "Konuşma metni", "share": "konuşma payı",
           "no_analysis": "Bu kayıt için toplantı analizi yapılmadı: özet, kararlar ve görevler yok.",
           "none": "Yok", "made_with": "Ses Defteri ile hazırlandı", "minutes": "tutanak"},
    "en": {"title": "Meeting Minutes", "date": "Date", "time": "Time", "length": "Length", "recording": "Recording",
           "participants": "Participants", "summary": "Summary", "chapters": "Agenda and chapters",
           "decisions": "Decisions", "tasks": "Tasks", "who": "Who", "what": "What", "when": "When",
           "questions": "Open questions", "transcript": "Transcript", "share": "of the talk",
           "no_analysis": "No meeting analysis was made for this recording: no summary, decisions or tasks.",
           "none": "None", "made_with": "Made with Ses Defteri", "minutes": "minutes"},
}

LIST_KEYS = {"kararlar", "aciksorular", "bolumler", "katilimcilistesi", "metin"}
ROW_PREFIX = "gorev."
_FOLD = str.maketrans("ıİçÇğĞöÖşŞüÜâÂîÎûÛ", "iiccggoossuuaaiiuu")
PLACEHOLDER = re.compile(r"\{([^{}\n]{1,40})\}")


def key_of(name: str) -> str:
    """'{Açık sorular}', '{acik_sorular}' and '{AÇIK-SORULAR}' are the same placeholder: 'aciksorular'."""
    s = name.strip().translate(_FOLD).lower()
    return re.sub(r"[^a-z0-9.]", "", s)


# ---------------------------------------------------------------- files and settings
def branding_dir() -> Path:
    d = store.data_dir() / "branding"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logo_path() -> Path | None:
    for ext in ("png", "jpg"):
        p = branding_dir() / f"logo.{ext}"
        if p.exists():
            return p
    return None


def template_path() -> Path:
    d = store.data_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tutanak.docx"


def clean_color(c) -> str:
    c = str(c or "").strip()
    return c.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else DEFAULT_COLOR


def clean_sections(v) -> list[str]:
    if not isinstance(v, list):
        return list(DEFAULT_SECTIONS)
    out = []
    for s in v:
        if s in SECTIONS and s not in out:
            out.append(s)
    return out


def config() -> dict:
    s = asr.get_settings()
    return {"company_name": str(s.get("company_name") or "")[:120], "company_color": clean_color(s.get("company_color")),
            "sections": clean_sections(s.get("minutes_sections")), "logo": bool(logo_path()),
            "template": template_path().exists()}


def set_logo(src: str) -> dict:
    p = Path(src)
    ext = p.suffix.lower().lstrip(".").replace("jpeg", "jpg")
    if ext not in ("png", "jpg"):
        raise ValueError("logo must be a PNG or JPG picture")
    if p.stat().st_size > MAX_LOGO:
        raise ValueError("logo is larger than 2 MB")
    data = p.read_bytes()
    if not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")):
        raise ValueError("not a picture file")
    try:  # Word must be able to place it
        from docx.image.image import Image

        Image.from_blob(data)
    except Exception:
        raise ValueError("this picture could not be read") from None
    remove_logo()
    (branding_dir() / f"logo.{ext}").write_bytes(p.read_bytes())
    return config()


def remove_logo() -> dict:
    for ext in ("png", "jpg"):
        (branding_dir() / f"logo.{ext}").unlink(missing_ok=True)
    return config()


def set_template(src: str) -> dict:
    p = Path(src)
    if p.suffix.lower() != ".docx":
        raise ValueError("the template must be a Word .docx file")
    if p.stat().st_size > MAX_TEMPLATE:
        raise ValueError("template is larger than 20 MB")
    from docx import Document

    try:
        Document(str(p))
    except Exception:
        raise ValueError("this Word file could not be opened") from None
    template_path().write_bytes(p.read_bytes())
    return config()


def remove_template() -> dict:
    template_path().unlink(missing_ok=True)
    return config()


# ---------------------------------------------------------------- content
def _clock(sec: float) -> str:
    sec = int(sec or 0)
    h, m = divmod(sec // 60, 60)
    return f"{h} sa {m} dk" if h else f"{m} dk"


def _clock_en(sec: float) -> str:
    sec = int(sec or 0)
    h, m = divmod(sec // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def participants(job: dict, analysis: dict | None, lang: str) -> list[dict]:
    """[{name, share}] by talk time, from the analysis statistics or the transcript itself."""
    stats = ((analysis or {}).get("stats") or {}).get("speakers") or []
    if stats:
        out = [{"name": export._spk(job, s.get("id"), lang), "share": s.get("share")} for s in stats]
    else:
        talk: dict[int, float] = {}
        for s in job.get("segments") or []:
            if (s.get("text_edited") or s.get("text_original") or "").strip():
                talk[s["speaker"]] = talk.get(s["speaker"], 0.0) + max(0.0, s["end"] - s["start"])
        total = sum(talk.values()) or 1.0
        out = [{"name": export._name(job, k, lang), "share": v / total}
               for k, v in sorted(talk.items(), key=lambda kv: -kv[1])]
    return [p for p in out if p["name"] != "—"]


def context(job: dict, analysis: dict | None, lang: str = "tr", company: str = "") -> dict:
    """Everything a minutes document can show, as text and lists (placeholder name -> value)."""
    L = LABELS[lang]
    a = analysis or {}
    when = datetime.datetime.fromtimestamp(float(job.get("created") or 0) or datetime.datetime.now().timestamp())
    people = participants(job, a, lang)
    pct = (lambda s: f"%{round(s * 100)}") if lang == "tr" else (lambda s: f"{round(s * 100)}%")
    chapters = a.get("chapters") or a.get("topics") or []
    tasks = [{"kim": export._spk(job, t.get("owner"), lang), "ne": str(t.get("task", "")), "tarih": str(t.get("due") or "")}
             for t in a.get("tasks") or []]
    lines = [f"[{export.ts(r['start'])}] {r['speaker']}: {r['text']}" for r in export.rows(job, "edited", lang)]
    return {
        "tarih": when.strftime("%d.%m.%Y") if lang == "tr" else when.strftime("%Y-%m-%d"),
        "saat": when.strftime("%H:%M"),
        "sure": (_clock if lang == "tr" else _clock_en)(job.get("duration") or 0),
        "kayit": Path(job.get("filename") or "").stem,
        "sirket": company,
        "baslik": L["title"],
        "ozet": str(a.get("summary") or ""),
        "katilimcilar": ", ".join(p["name"] for p in people),
        "katilimcilistesi": [f"{p['name']} ({pct(p['share'])} {L['share']})" if p.get("share") is not None else p["name"]
                             for p in people],
        "kararlar": [str(d.get("text", "")) for d in a.get("decisions") or []],
        "aciksorular": [(f"{export._spk(job, q.get('asker'), lang)}: " if q.get("asker") is not None else "") + str(q.get("text", ""))
                        for q in a.get("open_questions") or []],
        "bolumler": [(f"[{export.ts(c['start'])}] " if c.get("start") is not None else "") + str(c.get("title", ""))
                     + (f": {c['summary']}" if c.get("summary") else "") for c in chapters],
        "gorevler": tasks,
        "metin": lines,
        "_people": people,
        "_has_analysis": bool(a),
    }


# ---------------------------------------------------------------- built-in layout
def _rgb(hex_color: str):
    from docx.shared import RGBColor

    h = clean_color(hex_color).lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def builtin(ctx: dict, cfg: dict, lang: str = "tr", note_missing: bool = True) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    L = LABELS[lang]
    color = _rgb(cfg.get("company_color", DEFAULT_COLOR))
    grey = RGBColor(0x6B, 0x6F, 0x76)
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.2)

    # header: logo and company name
    hp = sec.header.paragraphs[0]
    logo = logo_path() if cfg.get("logo", True) else None
    if logo:
        try:
            hp.add_run().add_picture(str(logo), height=Cm(1.3))
            hp.add_run("   ")
        except Exception:  # a logo Word cannot read never blocks the minutes
            pass
    if cfg.get("company_name"):
        r = hp.add_run(cfg["company_name"])
        r.bold = True
        r.font.size = Pt(12)
        r.font.color.rgb = color

    def heading(text: str, size: int = 14):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(size)
        r.font.color.rgb = color
        return p

    def bullets(items: list[str]):
        if not items:
            doc.add_paragraph(L["none"]).runs[0].font.color.rgb = grey
        for it in items:
            doc.add_paragraph(it, style="List Bullet")

    title = heading(L["title"], 20)
    title.paragraph_format.space_before = Pt(0)
    sub = doc.add_paragraph()
    r = sub.add_run(ctx["kayit"])
    r.font.size = Pt(12)
    r.font.color.rgb = grey

    info = doc.add_table(rows=0, cols=2)
    info.style = "Table Grid"
    for k, v in ((L["date"], ctx["tarih"]), (L["time"], ctx["saat"]), (L["length"], ctx["sure"])):
        row = info.add_row().cells
        row[0].text, row[1].text = k, v
        row[0].paragraphs[0].runs[0].bold = True
        row[0].width, row[1].width = Cm(4), Cm(12)

    if note_missing and not ctx["_has_analysis"]:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        r = p.add_run(L["no_analysis"])
        r.italic = True
        r.font.color.rgb = grey

    needs_analysis = {"summary", "chapters", "decisions", "tasks", "questions"}
    for name in cfg.get("sections") or DEFAULT_SECTIONS:
        if name in needs_analysis and not ctx["_has_analysis"]:
            continue
        if name == "participants":
            heading(L["participants"])
            bullets(ctx["katilimcilistesi"])
        elif name == "summary":
            heading(L["summary"])
            doc.add_paragraph(ctx["ozet"] or L["none"])
        elif name == "chapters":
            heading(L["chapters"])
            bullets(ctx["bolumler"])
        elif name == "decisions":
            heading(L["decisions"])
            bullets(ctx["kararlar"])
        elif name == "tasks":
            heading(L["tasks"])
            if not ctx["gorevler"]:
                bullets([])
            else:
                tb = doc.add_table(rows=1, cols=3)
                tb.style = "Table Grid"
                for cell, txt in zip(tb.rows[0].cells, (L["who"], L["what"], L["when"])):
                    cell.text = txt
                    cell.paragraphs[0].runs[0].bold = True
                for t in ctx["gorevler"]:
                    c = tb.add_row().cells
                    c[0].text, c[1].text, c[2].text = t["kim"], t["ne"], t["tarih"] or "—"
                for row in tb.rows:
                    row.cells[0].width, row.cells[1].width, row.cells[2].width = Cm(4), Cm(9), Cm(3)
        elif name == "questions":
            heading(L["questions"])
            bullets(ctx["aciksorular"])
        elif name == "transcript":
            heading(L["transcript"])
            for line in ctx["metin"]:
                p = doc.add_paragraph(line)
                p.paragraph_format.space_after = Pt(2)

    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run(f"{L['made_with']} · {ctx['tarih']}")
    r.font.size = Pt(8)
    r.font.color.rgb = grey

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- user template
def _paragraphs_in(container):
    """Every paragraph of a body, cell, header or footer, tables included."""
    for p in container.paragraphs:
        yield p
    for t in getattr(container, "tables", []):
        for row in t.rows:
            for cell in row.cells:
                yield from _paragraphs_in(cell)


def _all_parts(doc):
    yield doc
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_header, s.first_page_footer, s.even_page_header, s.even_page_footer):
            try:
                if not part.is_linked_to_previous:  # only headers the template really has (no empty ones added)
                    yield part
            except Exception:
                continue


def _set_text(p, text: str) -> None:
    """Replace a paragraph's text, keeping the look of its first run (Word often splits '{özet}' over several runs)."""
    runs = p.runs
    if not runs:
        p.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def _scalar(value) -> str:
    if isinstance(value, list):
        return "; ".join(v if isinstance(v, str) else " ".join(str(x) for x in v.values()) for v in value)
    return str(value)


def _fill_rows(doc, ctx: dict) -> None:
    """A table row holding {görev.kim} / {görev.ne} / {görev.tarih} is repeated once per task."""
    def tables(container):
        for t in getattr(container, "tables", []):
            yield t
            for row in t.rows:
                for cell in row.cells:
                    yield from tables(cell)

    for part in _all_parts(doc):
        for t in list(tables(part)):
            for row in list(t.rows):
                keys = {key_of(m) for c in row.cells for m in PLACEHOLDER.findall(c.text)}
                if not any(k.startswith(ROW_PREFIX) for k in keys):
                    continue
                items = ctx["gorevler"] or [{"kim": "", "ne": LABELS["tr"]["none"], "tarih": ""}]
                anchor = row._tr
                for item in items:
                    tr = copy.deepcopy(row._tr)
                    anchor.addnext(tr)
                    anchor = tr
                    from docx.table import _Row

                    new = _Row(tr, t)
                    for cell in new.cells:
                        for p in cell.paragraphs:
                            if PLACEHOLDER.search(p.text):
                                _set_text(p, PLACEHOLDER.sub(
                                    lambda m: str(item.get(key_of(m.group(1))[len(ROW_PREFIX):], m.group(0)))
                                    if key_of(m.group(1)).startswith(ROW_PREFIX) else m.group(0), p.text))
                row._tr.getparent().remove(row._tr)


def fill_template(data: bytes, ctx: dict) -> bytes:
    from docx import Document
    from docx.shared import Cm

    doc = Document(io.BytesIO(data))
    _fill_rows(doc, ctx)
    values = {k: v for k, v in ctx.items() if not k.startswith("_")}
    logo = logo_path()
    for part in _all_parts(doc):
        for p in list(_paragraphs_in(part)):
            text = p.text
            found = PLACEHOLDER.findall(text)
            if not found:
                continue
            alone = text.strip()
            k = key_of(found[0]) if len(found) == 1 and alone == "{" + found[0] + "}" else None
            if k == "logo":
                _set_text(p, "")
                if logo:
                    try:
                        p.runs[0].add_picture(str(logo), height=Cm(1.5))
                    except Exception:
                        pass
                continue
            if k in LIST_KEYS and isinstance(values.get(k), list):
                items = values[k] or [LABELS["tr"]["none"]]
                anchor = p._p
                for it in items[1:]:
                    np_ = copy.deepcopy(p._p)
                    anchor.addnext(np_)
                    anchor = np_
                    from docx.text.paragraph import Paragraph

                    _set_text(Paragraph(np_, p._parent), it)
                _set_text(p, items[0])
                continue

            def sub(m):
                key = key_of(m.group(1))
                if key == "logo":
                    return ""
                return _scalar(values[key]) if key in values else m.group(0)
            _set_text(p, PLACEHOLDER.sub(sub, text))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- entry point
def build(job: dict, analysis: dict | None, lang: str = "tr", use_template: bool = True,
          note_missing: bool = True, sections: list[str] | None = None) -> bytes:
    """sections overrides the Settings choice (the simple edition: participants + transcript, it has no analysis)."""
    lang = lang if lang in LABELS else "tr"
    cfg = config()
    if sections is not None:
        cfg["sections"] = clean_sections(sections)
    ctx = context(job, analysis, lang, cfg["company_name"])
    if use_template and template_path().exists():
        return fill_template(template_path().read_bytes(), ctx)
    return builtin(ctx, cfg, lang, note_missing)


def sample_template(lang: str = "tr") -> bytes:
    """A starter template that shows every placeholder (assets/tutanak-ornek.docx is the same, made at build time)."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "{logo}"
    hp = doc.sections[0].header.add_paragraph("{şirket}")
    hp.runs[0].bold = True
    doc.add_heading("Toplantı Tutanağı", 0)
    doc.add_paragraph("Kayıt: {kayıt}")
    doc.add_paragraph("Tarih: {tarih}   Saat: {saat}   Süre: {süre}")
    doc.add_paragraph("Katılımcılar: {katılımcılar}")
    doc.add_heading("Özet", 1)
    doc.add_paragraph("{özet}")
    doc.add_heading("Bölümler", 1)
    doc.add_paragraph("{bölümler}", style="List Bullet")
    doc.add_heading("Kararlar", 1)
    doc.add_paragraph("{kararlar}", style="List Bullet")
    doc.add_heading("Görevler", 1)
    t = doc.add_table(rows=2, cols=3)
    t.style = "Table Grid"
    for c, txt in zip(t.rows[0].cells, ("Kim", "Ne", "Ne zaman")):
        c.text = txt
    for c, txt in zip(t.rows[1].cells, ("{görev.kim}", "{görev.ne}", "{görev.tarih}")):
        c.text = txt
    doc.add_heading("Açık sorular", 1)
    doc.add_paragraph("{açık_sorular}", style="List Bullet")
    doc.add_heading("Yer tutucular", 1)
    help_ = doc.add_paragraph()
    r = help_.add_run(
        "Bu sayfayı silebilirsiniz. Kendi şablonunuzda süslü parantez içindeki adları kullanın; Ses Defteri onları "
        "doldurur. Adlar Türkçe harfli ya da harfsiz yazılabilir (özet = ozet).\n"
        "Tek değerler: tarih, saat, süre, kayıt, şirket, başlık, özet, katılımcılar.\n"
        "Listeler (paragrafta tek başına yazın, her madde için paragraf çoğaltılır): kararlar, açık_sorular, "
        "bölümler, katılımcı_listesi, metin (tam konuşma metni).\n"
        "Görev tablosu: bir satıra görev.kim, görev.ne, görev.tarih yazın; satır her görev için çoğaltılır.\n"
        "Logo: süslü parantez içinde logo, tek başına bir paragrafta (Ayarlar sayfasında yüklenen logo).")
    r.font.size = Pt(9)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
