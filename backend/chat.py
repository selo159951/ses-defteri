"""AI assistant: questions about the recordings, answered on this PC with the meeting-mode model.

"What did Ahmet say about the app last week?" is answered in four steps; only steps 2 and 4 use the model:
1. dates by code (reliable): "geçen hafta" = Monday-Sunday of the previous week, "dün", "3 gün önce", "bu ay"…
2. the model reads the question: about the recordings, about the app, or something else; which people, which words,
   whether it asks for decisions / tasks / open questions / a summary;
3. search by code in the local database (chatdb): date range + people + words (+ meaning search when installed);
4. the model answers from the numbered lines it was given, citing them; the citations are checked by code.

Rules: answers come only from the recordings (or the facts about the app below); "not found" when nothing matches,
never invented; other topics are politely declined. A small model can still misread: every answer links to its
sources so it can be checked.
"""
from __future__ import annotations

import datetime as dt
import re

from . import chatdb, chats

CREDITS = {"tr": "Ses Defteri'nin fikir babası Umut Akbaş, geliştiricisi Selim Oğuz'dur (Claude ile birlikte).",
           "en": "Ses Defteri was thought up by Umut Akbaş and developed by Selim Oğuz (together with Claude)."}
APP_FACTS = {
    "tr": ("Ses Defteri toplantı kayıtlarını konuşmacılarıyla birlikte düzenlenebilir metne çevirir, tamamen bu "
           "bilgisayarda ve internetsiz çalışır. Özellikleri: dosya sürükle-bırak, programın içinden toplantı kaydı "
           "(bilgisayar sesi + mikrofon) ve isteğe bağlı canlı yazı, konuşmacı ayırma, Kişiler sayfasında kayıtlı "
           "seslerle isim verme, metni düzenleme, anlamına göre arama, toplantı analizi (özet, kararlar, görevler, "
           "açık sorular, puan), Word tutanak (şirket logosu ve kendi şablonu), Word/TXT/Markdown/SRT/JSON dışa "
           "aktarma, gürültü temizleme, klasör izleme, otomatik güncelleme. " + CREDITS["tr"]),
    "en": ("Ses Defteri turns meeting recordings into editable transcripts with speakers, fully on this computer and "
           "offline. Features: drag & drop, recording meetings inside the app (computer sound + microphone) with "
           "optional live text, speaker separation, naming people by their saved voices, editing, search by meaning, "
           "meeting analysis (summary, decisions, tasks, open questions, score), Word minutes (company logo and own "
           "template), export to Word/TXT/Markdown/SRT/JSON, noise cleanup, folder watch, automatic updates. "
           + CREDITS["en"]),
}
TEXT = {
    "tr": {"off_topic": "Bu konuda yardımcı olamıyorum; ben toplantı kayıtlarınızı ve Ses Defteri'ni biliyorum. "
                        "Şöyle sorabilirsiniz: \"Dünkü toplantıda neler konuşuldu?\", \"Geçen hafta hangi kararlar alındı?\", "
                        "\"Ahmet fiyat hakkında ne dedi?\"",
           "not_found": "Bu soruya uyan bir kayıt bulamadım{when}.", "when": " ({r})",
           "no_rec_in_range": "{r} tarihinde kayıt yok.", "nearest": " En yakın kayıtlar: {d}.",
           "vague": "Hangi toplantıyı, kişiyi ya da konuyu soruyorsunuz? Örneğin: \"Bugünkü toplantının özeti\", "
                    "\"Geçen hafta Ahmet ne dedi?\", \"Fiyat artışı hakkında neler konuşuldu?\"",
           "no_records": "Henüz metne çevrilmiş bir kayıt yok."},
    "en": {"off_topic": "I can't help with that; I know your meeting recordings and Ses Defteri. Try: \"What did we "
                        "discuss yesterday?\", \"Which decisions were made last week?\", \"What did Ahmet say about the price?\"",
           "not_found": "I could not find a recording that matches{when}.", "when": " ({r})",
           "no_rec_in_range": "There is no recording on {r}.", "nearest": " Nearest recordings: {d}.",
           "vague": "Which meeting, person or topic do you mean? For example: \"Summary of today's meeting\", "
                    "\"What did Ahmet say last week?\", \"What was said about the price rise?\"",
           "no_records": "There are no transcribed recordings yet."},
}
# greetings, thanks, "how are you": answered at once, without the model (folded text, whole message)
_SMALL_TALK = [
    (r"(selam(lar)?|merhaba(lar)?|sa|slm|mrb|iyi (gunler|aksamlar|sabahlar)|gunaydin|hey|hi|hello|good (morning|evening))",
     {"tr": "Merhaba! Toplantılarınız hakkında ne öğrenmek istersiniz? Örneğin \"Dünkü toplantıda neler konuşuldu?\"",
      "en": "Hello! What would you like to know about your meetings? For example \"What did we discuss yesterday?\""}),
    (r"(nasilsin(iz)?|naber|ne haber|how are you)",
     {"tr": "İyiyim, teşekkürler! Toplantılarınızla ilgili bir soru sorabilirsiniz.",
      "en": "I'm fine, thanks! Ask me anything about your meetings."}),
    (r"(tesekkur(ler| ederim)?|sag ?ol(un)?|eyvallah|tsk|tskler|thanks?( you)?|ty)",
     {"tr": "Rica ederim! Başka bir sorunuz olursa buradayım.", "en": "You're welcome! I'm here if you need anything else."}),
    (r"(tamam|ok|okay|peki|anladim|super|harika|guzel)",
     {"tr": "Tamam. Başka bir şey sormak isterseniz yazabilirsiniz.", "en": "Okay. Ask me anything else whenever you like."}),
]


def small_talk(question: str, lang: str) -> str | None:
    q = re.sub(r"[^\w\s]", " ", chatdb.fold(question)).strip()
    q = re.sub(r"\s+", " ", q)
    any_ = "|".join(p for p, _ in _SMALL_TALK)
    if not q or not re.fullmatch(rf"(?:{any_})(?: (?:{any_}))*", q):  # "selam nasılsın" too, but not "selam, dün ne konuştuk"
        return None
    # the last part decides: "selam nasılsın" -> how are you
    last = next((text for pat, text in _SMALL_TALK if re.search(rf"(?:^| )(?:{pat})$", q)), _SMALL_TALK[0][1])
    return last[lang]


TITLE_SCHEMA = {"type": "object", "properties": {"baslik": {"type": "string"}}, "required": ["baslik"]}


def make_title(question: str, answer: str, lang: str = "tr", generate=None) -> str:
    """A short title for a saved conversation, written by the model in the question's language.
    Small talk is not worth a model call; any problem falls back to the first words of the question."""
    lang = lang if lang in TEXT else "tr"
    if small_talk(question, lang) is not None:
        return chats.fallback_title(question)
    if generate is None:
        from . import llm

        generate = llm.generate
    system = ("Bu sohbet için 2-5 kelimelik kısa bir başlık üret. "
              f"{'Türkçe' if lang == 'tr' else 'English'} yaz. Sadece başlığı yaz: tırnak işareti ve nokta olmadan.")
    try:
        # a schema, like the other calls: free text from a thinking model can be cut off inside its thinking
        out = generate(f"Soru: {question}\n\nCevap: {(answer or '')[:400]}", schema=TITLE_SCHEMA, system=system,
                       max_tokens=80, temperature=0.2)
        out = str(out.get("baslik") or "") if isinstance(out, dict) else str(out)
        out = out.strip().splitlines()[0].strip() if out.strip() else ""
        out = re.sub(r"[*_`#>]+", "", out).strip().strip("\"'“”‘’").strip().rstrip(" .,!?…:;").strip()
        if out:
            return out[:chats.TITLE_MAX].rstrip(" .,!?…:;").strip()
    except Exception:
        pass  # a title is a bonus: the question's first words are always there
    return chats.fallback_title(question)


DAYS_TR = ["pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar"]
DAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS_TR = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december"]
KIND_OF = {"karar": ["decision"], "gorev": ["task"], "soru": ["question"], "ozet": ["summary"], "genel": None}
MAX_SOURCES = 20


# ---------------------------------------------------------------- 1. dates
def _day(d: dt.date) -> float:
    return dt.datetime.combine(d, dt.time()).timestamp()


def resolve_dates(question: str, now: dt.datetime | None = None) -> tuple[float, float, str] | None:
    """(from, to, label) for the time words in the question, or None. Weeks run Monday to Sunday."""
    now = now or dt.datetime.now()
    today = now.date()
    q = chatdb.fold(question)
    monday = today - dt.timedelta(days=today.weekday())

    def rng(a: dt.date, b: dt.date, label: str):
        return _day(a), _day(b), label

    m = re.search(r"\b(?:son|last|past)\s+(\d{1,3})\s*(gun|gün|days?|hafta|weeks?|ay|months?)\b", q)
    if m:
        n, unit = int(m[1]), m[2]
        days = n * (7 if unit.startswith(("hafta", "week")) else 30 if unit.startswith(("ay", "month")) else 1)
        return rng(today - dt.timedelta(days=days - 1), today + dt.timedelta(days=1), m[0])
    m = re.search(r"\b(\d{1,3})\s*(gun|days?|hafta|weeks?|ay|months?)\s*(?:once|onceki|ago)\b", q)
    if m:
        n, unit = int(m[1]), m[2]
        if unit.startswith(("hafta", "week")):
            start = monday - dt.timedelta(weeks=n)
            return rng(start, start + dt.timedelta(days=7), m[0])
        if unit.startswith(("ay", "month")):
            y, mo = today.year, today.month - n
            while mo < 1:
                mo += 12; y -= 1
            start = dt.date(y, mo, 1)
            end = dt.date(y + (mo == 12), mo % 12 + 1, 1)
            return rng(start, end, m[0])
        d = today - dt.timedelta(days=n)
        return rng(d, d + dt.timedelta(days=1), m[0])
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b", q)  # full dates only: "1.5 milyon" is not a date
    if m:
        y = int(m[3])
        y = y + 2000 if y < 100 else y
        try:
            d = dt.date(y, int(m[2]), int(m[1]))
            return rng(d, d + dt.timedelta(days=1), m[0])
        except ValueError:
            pass
    for names in (MONTHS_TR, MONTHS_EN):
        for i, name in enumerate(names):
            m = re.search(rf"\b(\d{{1,2}})\s+{name}\w*\b", q)
            if m:
                y = today.year if (i + 1, int(m[1])) <= (today.month, today.day) else today.year - 1
                try:
                    d = dt.date(y, i + 1, int(m[1]))
                    return rng(d, d + dt.timedelta(days=1), m[0])
                except ValueError:
                    pass
    table = [
        (r"\b(evvelsi gun|onceki gun|day before yesterday)\b", lambda: (today - dt.timedelta(days=2), today - dt.timedelta(days=1))),
        (r"\b(dun|dunku|yesterday)\b", lambda: (today - dt.timedelta(days=1), today)),
        (r"\b(bugun|bugunku|today)\b", lambda: (today, today + dt.timedelta(days=1))),
        (r"\b(gecen hafta|gecen haftaki|onceki hafta|last week)\b", lambda: (monday - dt.timedelta(days=7), monday)),
        (r"\b(bu hafta|bu haftaki|this week)\b", lambda: (monday, today + dt.timedelta(days=1))),
        (r"\b(gecen ay|gecen ayki|last month)\b", lambda: (
            dt.date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1), dt.date(today.year, today.month, 1))),
        (r"\b(bu ay|bu ayki|this month)\b", lambda: (dt.date(today.year, today.month, 1), today + dt.timedelta(days=1))),
        (r"\b(gecen yil|gecen sene|last year)\b", lambda: (dt.date(today.year - 1, 1, 1), dt.date(today.year, 1, 1))),
        (r"\b(bu yil|bu sene|this year)\b", lambda: (dt.date(today.year, 1, 1), today + dt.timedelta(days=1))),
    ]
    for pat, f in table:
        m = re.search(pat, q)
        if m:
            a, b = f()
            return rng(a, b, m[0])
    for names in (DAYS_TR, DAYS_EN):
        for i, name in enumerate(names):
            # only "geçen salı", "salı günü", "salıki toplantı", "on monday": "sürüm cuma çıkacak mı" is no date
            m = re.search(rf"\b(gecen\s+|last\s+|on\s+)?{name}(ki|daki|deki)?(\s+(?:gunu|gunku|toplanti\w*|meeting))?\b", q)
            if m and (m[1] or m[2] or m[3]):  # "on monday" / "pazartesi günü" = the most recent one
                last = bool(re.match(r"(gecen|last)\s", m[0]))
                back = (today.weekday() - i) % 7
                if last and (today - dt.timedelta(days=back)) >= monday:
                    back += 7  # "geçen salı": the one in the previous week
                d = today - dt.timedelta(days=back)
                return rng(d, d + dt.timedelta(days=1), m[0])
    return None


def describe_range(a: float, b: float, lang: str) -> str:
    da, db = dt.date.fromtimestamp(a), dt.date.fromtimestamp(b) - dt.timedelta(days=1)
    f = (lambda d: d.strftime("%d.%m.%Y")) if lang == "tr" else (lambda d: d.isoformat())
    return f(da) if da == db else f"{f(da)} – {f(db)}"


# ---------------------------------------------------------------- 2. what is asked
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "niyet": {"type": "string", "enum": ["kayit", "uygulama", "kapsam_disi"]},
        "tur": {"type": "string", "enum": ["genel", "karar", "gorev", "soru", "ozet"]},
        "kisiler": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "anahtar": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["niyet", "tur", "kisiler", "anahtar"],
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "cevap": {"type": "string"},
        "kaynaklar": {"type": "array", "items": {"type": "integer"}, "maxItems": 8},
        "bulundu": {"type": "boolean"},
    },
    "required": ["cevap", "kaynaklar", "bulundu"],
}


def people_block(people: list[dict]) -> str:
    rows = []
    for p in people:
        bits = [p["name"]] + [x for x in (p.get("title"), p.get("note")) if x]
        rows.append("- " + " — ".join(bits))
    return "\n".join(rows) or "- (kayıtlı kişi yok)"


def intent_prompt(question: str, today: dt.date, people: list[dict], history: list[dict]) -> tuple[str, str]:
    day = DAYS_TR[today.weekday()]
    system = (
        "Sen Ses Defteri uygulamasının asistanısın. Kullanıcının sorusunu sınıflandır, cevap verme.\n"
        f"Bugün: {today.strftime('%d.%m.%Y')} ({day}).\n"
        "niyet: 'kayit' = toplantı kayıtlarında konuşulanlar, kararlar, görevler, kişilerin söyledikleri hakkında; "
        "'uygulama' = Ses Defteri programının kendisi, özellikleri, kimin yaptığı hakkında; "
        "'kapsam_disi' = bunların dışında her şey (genel bilgi, kod, hava durumu, sohbet, çeviri…).\n"
        "tur: 'karar' kararlar, 'gorev' görevler/yapılacaklar, 'soru' açık sorular, 'ozet' özet/neler konuşuldu, "
        "'genel' diğer.\n"
        "kisiler: soruda adı geçen kişiler (yalın hâliyle: 'Ahmet'in' -> 'Ahmet').\n"
        "anahtar: aranacak konu kelimeleri (en fazla 6; isimleri, tarihleri ve 'ne dedi', 'toplantı' gibi genel "
        "kelimeleri yazma). Eş anlamlıları da ekleyebilirsin (zam -> fiyat artışı).\n"
        "Kayıtlı kişiler:\n" + people_block(people))
    prev = ""
    for h in history[-3:]:
        prev += f"Önceki soru: {h.get('q', '')}\n"
    return system, prev + f"Soru: {question}"


# What kind of thing is asked is decided by code: a 4B model often reads "ne demişti?" as "open questions".
_KIND_WORDS = [
    ("karar", r"\bkarar\w*|\bdecision\w*|\bdecided\b"),
    ("gorev", r"\bgorev\w*|\byapilacak\w*|\bis(ler)?i? (verildi|dagitildi)|\btask\w*|\bto-?dos?\b|\baction items?\b"),
    ("soru", r"\bacik soru\w*|\bcevapsiz\w*|\bopen questions?\b|\bunanswered\b"),
    ("ozet", r"\bozet\w*|\bneler konus\w*|\bne konus\w*|\bsummar\w*|\bwhat (was|did we) (discuss|talk)\w*"),
]
# words that say nothing about the topic (folded); removed from the model's search words
_STOP = {"ne", "neler", "nedir", "dedi", "demis", "demisti", "soyledi", "soylemisti", "soyle", "konustu", "konusuldu",
         "konustuk", "bahsetti", "bahsettik", "hakkinda", "icin", "ile", "mi", "mu", "mı", "bir", "bu", "su", "ve",
         "toplanti", "toplantida", "toplantisi", "toplantilar", "kayit", "kayitlar", "bugun", "bugunku", "dun",
         "gecen", "hafta", "haftaki", "ay", "kim", "kimin", "nasil", "neden", "what", "did", "say", "said", "about",
         "the", "meeting", "meetings", "last", "week", "today", "who", "which", "was", "were", "karar", "kararlar",
         "gorev", "gorevler", "soru", "sorular", "ozet", "konusma", "konusmalar", "soz", "sozler", "sozleri",
         "dunku", "demek", "istedi", "anlatti"} | set(MONTHS_TR) | set(MONTHS_EN) | set(DAYS_TR) | set(DAYS_EN)


def kind_of_question(question: str) -> str:
    q = chatdb.fold(question)
    return next((k for k, pat in _KIND_WORDS if re.search(pat, q)), "genel")


def clean_words(words: list[str], people: list[str]) -> list[str]:
    names = {chatdb.fold(n) for p in people for n in p.split()}
    out = []
    for w in words:
        parts = [p for p in re.split(r"\s+", w.strip()) if p]
        keep = [p for p in parts if chatdb.fold(p).strip(".,?!'\"") not in _STOP and chatdb.stem(p) not in names
                and len(chatdb.stem(p)) >= 3]
        if keep:
            out.append(" ".join(keep))
    return list(dict.fromkeys(out))[:6]


def in_recordings(words: list[str]) -> bool:
    """True when one line of the recordings has at least two of the words (or the only one): a single common word
    ("liste", "hava") is not enough to call a general question a question about the meetings."""
    words = [w for w in words if w.strip()][:6]
    if not words:
        return False
    need = min(2, len(words))
    hits: dict[int, int] = {}
    for w in words:
        for r in chatdb.search([w], limit=200):
            hits[r["rowid"]] = hits.get(r["rowid"], 0) + 1
    return any(n >= need for n in hits.values())


def tidy(text: str) -> str:
    """The page shows plain text: no **bold** marks; the app name spelled right."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m[1] or m[2], text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", text)
    text = re.sub(r"\s*(Kaynak(lar)?|Sources?)\s*:?\s*$", "", text, flags=re.I)  # the sources are shown as chips
    text = re.sub(r"\bSes\s?Def[a-z]*ti\b", "Ses Defteri", text)
    return text.strip()


# ---------------------------------------------------------------- 3. search
def gather(intent: dict, when: tuple | None, semantic=None, limit: int = MAX_SOURCES) -> list[dict]:
    speakers = chatdb.people_in(intent.get("kisiler") or [])
    if intent.get("kisiler") and not speakers:
        return []  # the person never spoke in any recording
    words = [w for w in intent.get("anahtar") or [] if w.strip()]
    kinds = KIND_OF.get(intent.get("tur") or "genel")
    a, b = (when[0], when[1]) if when else (None, None)
    found: dict[int, dict] = {}

    def add(rows):
        for r in rows:
            if r["rowid"] not in found and len(found) < limit:
                found[r["rowid"]] = r
    if kinds:  # decisions / tasks / …: the analysis items, matching words first
        if words:
            add(chatdb.search(words, a, b, speakers if kinds != ["summary"] else None, kinds, limit))
        add(chatdb.search(None, a, b, speakers if kinds != ["summary"] else None, kinds, limit))
    if words:
        add(chatdb.search(words, a, b, speakers, ["line", "decision", "task", "question"], limit))
        if semantic and len(found) < limit:
            try:
                add(semantic(" ".join(words), a, b, speakers))
            except Exception:
                pass
    if not found and not kinds and (speakers or when or not words):
        # "what did Ahmet say last week": that person's lines, or the summaries of those meetings. Also when the
        # model's search words matched nothing but the person / date narrow it down enough.
        add(chatdb.search(None, a, b, speakers, ["line"] if speakers else ["summary"], limit))
    return list(found.values())[:limit]


def semantic_rows(query: str, a, b, speakers) -> list[dict]:
    """Meaning search (when its model is installed), mapped onto the database rows with the same filters."""
    from . import semantic

    res = semantic.search(query, limit=20).get("results") or []
    rows = [chatdb.line_at(r["job_id"], r["seg"], a, b, speakers) for r in res]
    return [r for r in rows if r]


# ---------------------------------------------------------------- 4. answer
def _stamp(sec: float) -> str:
    sec = int(sec or 0)
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def source_lines(rows: list[dict], lang: str) -> list[str]:
    label = {"line": "", "summary": "özet" if lang == "tr" else "summary", "decision": "karar" if lang == "tr" else "decision",
             "task": "görev" if lang == "tr" else "task", "question": "açık soru" if lang == "tr" else "open question"}
    out = []
    for i, r in enumerate(rows, 1):
        date = dt.date.fromtimestamp(r["created"] or 0).strftime("%d.%m.%Y")
        head = [r["filename"], date]
        if r["kind"] != "summary" and r.get("start") is not None:
            head.append(_stamp(r["start"]))
        if label[r["kind"]]:
            head.append(label[r["kind"]])
        if r.get("speaker"):
            head.append(r["speaker"])
        text = r["text"]
        if r["kind"] == "line" and r.get("seg") is not None:  # the thought around it
            ctx = chatdb.context(r["job_id"], r["seg"], 1)
            if len(ctx) > 1:
                text = " / ".join(f"{c['speaker']}: {c['text']}" for c in ctx)
        out.append(f"[{i}] ({', '.join(head)}) {text[:600]}")
    return out


def answer_prompt(question: str, rows: list[dict], lang: str, today: dt.date, when_label: str) -> tuple[str, str]:
    system = (
        "Sen Ses Defteri'nin asistanısın. Kurallar:\n"
        "1. Yalnızca aşağıda numaralı verilen kayıt satırlarına dayanarak cevap ver. Bilgin yoksa uydurma.\n"
        "2. Satırlarda cevap yoksa bulundu=false yap ve bunu kısaca söyle.\n"
        "3. Kullandığın satırların numaralarını kaynaklar listesine yaz.\n"
        "4. Kısa ve net yaz (en fazla 5 cümle ya da madde). Kimin ne dediğini adıyla belirt.\n"
        f"5. {'Türkçe' if lang == 'tr' else 'English'} cevap ver.\n"
        f"Bugün: {today.strftime('%d.%m.%Y')}." + (f" Soru şu tarihleri kapsıyor: {when_label}." if when_label else ""))
    return system, "Kayıt satırları:\n" + "\n".join(source_lines(rows, lang)) + f"\n\nSoru: {question}"


# ---------------------------------------------------------------- the whole question
def ask(question: str, history: list[dict] | None = None, lang: str = "tr", generate=None, people: list[dict] | None = None,
        now: dt.datetime | None = None, semantic=None, cancel=None) -> dict:
    """{"answer", "sources": [...], "found", "intent", "range"}."""
    lang = lang if lang in TEXT else "tr"
    T = TEXT[lang]
    question = (question or "").strip()[:500]
    history = history or []
    now = now or dt.datetime.now()
    if generate is None:
        from . import llm

        generate = llm.generate
    if people is None:
        from . import people as people_mod

        people = people_mod.list_people()
    reply = small_talk(question, lang)
    if reply:
        return {"answer": reply, "sources": [], "found": True, "intent": {"niyet": "sohbet"}, "range": ""}
    chatdb.sync()

    system, prompt = intent_prompt(question, now.date(), people, history)
    intent = generate(prompt, schema=INTENT_SCHEMA, system=system, max_tokens=300, temperature=0.1, cancel=cancel)
    kisiler = [str(x) for x in intent.get("kisiler") or []][:4]
    intent = {"niyet": intent.get("niyet", "kayit"), "tur": kind_of_question(question), "kisiler": kisiler,
              "anahtar": clean_words([str(x) for x in intent.get("anahtar") or []], kisiler)}

    if intent["niyet"] == "kapsam_disi":
        # a small model sometimes calls a real meeting question off topic ("Reklam bütçesini kim onaylayacak?"):
        # when the words of the question are said together in a recording, it is about the recordings after all
        words = intent["anahtar"] or clean_words(question.split(), kisiler)
        if not in_recordings(words):
            return {"answer": T["off_topic"], "sources": [], "found": False, "intent": intent, "range": ""}
        intent = {**intent, "niyet": "kayit", "anahtar": words}
    if intent["niyet"] == "uygulama":
        sys2 = (f"Sen Ses Defteri'nin asistanısın. Yalnızca şu bilgilere dayanarak {'Türkçe' if lang == 'tr' else 'English'}"
                f" ve kısa cevap ver, bilmediğin şeyi uydurma:\n{APP_FACTS[lang]}")
        text = generate(f"Soru: {question}", system=sys2, max_tokens=400, temperature=0.2, cancel=cancel)
        return {"answer": tidy(str(text)), "sources": [], "found": True, "intent": intent, "range": ""}

    when = resolve_dates(question, now)
    if not when and (intent["kisiler"] or intent["anahtar"]):
        # "and what about Umut?": keep the dates of the previous question (only for a real follow-up)
        for h in reversed(history[-3:]):
            if h.get("range_ts"):
                when = (h["range_ts"][0], h["range_ts"][1], h.get("range", ""))
                break
    label = describe_range(when[0], when[1], lang) if when else ""
    if chatdb.counts()["recordings"] == 0:
        return {"answer": T["no_records"], "sources": [], "found": False, "intent": intent, "range": label}
    if not (when or intent["kisiler"] or intent["anahtar"] or intent["tur"] != "genel"):
        return {"answer": T["vague"], "sources": [], "found": False, "intent": intent, "range": ""}
    if when and not chatdb.recording_dates(when[0], when[1], limit=1):
        near = chatdb.recording_dates(near=(when[0] + when[1]) / 2)
        days = ", ".join(dict.fromkeys(dt.date.fromtimestamp(t).strftime("%d.%m.%Y") for t in sorted(near)))
        text = T["no_rec_in_range"].format(r=label) + (T["nearest"].format(d=days) if days else "")
        return {"answer": text, "sources": [], "found": False, "intent": intent, "range": label,
                "range_ts": [when[0], when[1]]}
    rows = gather(intent, when, semantic)
    speakers = chatdb.people_in(intent["kisiler"]) if intent["kisiler"] else None
    if not rows and when and speakers != []:  # recordings on those days, but no analysis / no matching word
        rows = (None if speakers else chatdb.search(None, when[0], when[1], None, ["summary"], MAX_SOURCES)) \
            or chatdb.search(None, when[0], when[1], speakers, ["line"], MAX_SOURCES)
    if not rows:
        return {"answer": T["not_found"].format(when=T["when"].format(r=label) if label else ""), "sources": [],
                "found": False, "intent": intent, "range": label, "range_ts": [when[0], when[1]] if when else None}

    system, prompt = answer_prompt(question, rows, lang, now.date(), label)
    out = generate(prompt, schema=ANSWER_SCHEMA, system=system, max_tokens=700, temperature=0.2, cancel=cancel)
    cited = [n for n in out.get("kaynaklar") or [] if isinstance(n, int) and 1 <= n <= len(rows)]
    cited = list(dict.fromkeys(cited))  # no made-up or repeated numbers
    sources = [{"n": n, "job_id": rows[n - 1]["job_id"], "filename": rows[n - 1]["filename"],
                "created": rows[n - 1]["created"], "start": rows[n - 1]["start"], "seg": rows[n - 1]["seg"],
                "speaker": rows[n - 1]["speaker"], "kind": rows[n - 1]["kind"], "text": rows[n - 1]["text"][:240]}
               for n in cited]
    text = tidy(re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", str(out.get("cevap") or "")))  # numbers live in the chips
    found = bool(out.get("bulundu")) and bool(sources)
    if not text:
        text = T["not_found"].format(when="")
    return {"answer": text, "sources": sources, "found": found, "intent": intent, "range": label,
            "range_ts": [when[0], when[1]] if when else None}
