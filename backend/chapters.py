"""Chapters ("Bolumler"): the meeting split into topic sections, each with a title, a time range and
one or two sentences. The local model only proposes where a new topic starts (a segment id) and names
the section; everything else (order, ends, minimum length, merging across windows) is done here.

A long transcript is read in windows; the title of the last chapter of a window is given to the next one
so a topic that crosses the window border is not started twice, and neighbours that still say the same
thing are merged afterwards.
"""
from __future__ import annotations

import bisect

WINDOW_TOKENS = 4500       # one model call reads about this much transcript
MIN_CHAPTER_SECONDS = 60   # a shorter section is folded into its neighbour
NONE_BELOW = 120           # under two minutes there is nothing to divide
SHORT_BELOW = 300          # under five minutes: at most two chapters
SECONDS_PER_CHAPTER = 110  # about one chapter per two minutes at most

_S, _I = {"type": "string"}, {"type": "integer"}


def schema(max_chapters: int) -> dict:
    item = {"type": "object", "properties": {"line": _I, "title": {"type": "string", "minLength": 3},
                                             "summary": {"type": "string", "minLength": 15}},
            "required": ["line", "title", "summary"]}
    return {"type": "object", "required": ["chapters"], "properties": {
        "chapters": {"type": "array", "items": item, "minItems": 1, "maxItems": max(1, max_chapters)}}}


SYSTEM = {
    "tr": ("Sen bir toplantı analiz asistanısın. Yalnızca verilen konuşma dökümüne dayan; "
           "dökümde olmayan hiçbir şeyi uydurma. Satır numaralarını köşeli parantezdeki sayıdan al. "
           "Kısa ve net yaz. Cevabı Türkçe yaz."),
    "en": ("You are a meeting analysis assistant. Rely only on the given transcript; "
           "never invent anything that is not in it. Take line numbers from the number in square brackets. "
           "Write short and plain. Answer in English."),
}
PROMPT = {
    "tr": """Aşağıda bir toplantı dökümü var. Her satır: [satır no] [zaman] Konuşmacı: metin.
Görevin: toplantıyı konu değişimlerine göre BÖLÜMLERE ayırmak. En fazla {max} bölüm yaz.
- line: bölümün BAŞLADIĞI satırın numarası (köşeli parantezdeki sayı). Bölümler artan sırada olsun.
- title: 2-6 kelimelik kısa başlık (örnek: "Sürüm tarihi", "Bildirim kapsamı").
- summary: bölümde ne konuşulup ne sonuçlandığını anlatan 1-2 cümle.
- Konu aynı sürüyorsa bölme. Selamlaşma ve laf arası ayrı bölüm olmaz; ilk bölüm ilk satırdan başlasın.
{previous}
Döküm:
{transcript}""",
    "en": """Below is a meeting transcript. Each line: [line no] [time] Speaker: text.
Your task: divide the meeting into CHAPTERS by topic change. Write at most {max} chapters.
- line: the number of the line where the chapter STARTS (the number in square brackets). Keep them in increasing order.
- title: a short title of 2-6 words (for example "Release date", "Notification scope").
- summary: 1-2 sentences on what was discussed and settled in the chapter.
- Do not split while the topic goes on. Greetings and small talk are not a chapter; the first chapter starts at the first line.
{previous}
Transcript:
{transcript}""",
}
PREVIOUS = {
    "tr": "Önceki bölümün son konusu: \"{title}\". Bu döküm hâlâ o konuyla başlıyorsa ilk bölümü aynı başlıkla yaz.\n",
    "en": "The topic before this part ended on: \"{title}\". If this transcript still starts on that topic, give the first chapter the same title.\n",
}


def max_chapters(duration: float) -> int:
    if duration < NONE_BELOW:
        return 0
    if duration < SHORT_BELOW:
        return 2
    return max(2, min(40, int(duration // SECONDS_PER_CHAPTER)))


def windows(lines: list[str], limit: int | None = None) -> list[list[str]]:
    from . import analysis

    return analysis.chunk_lines(lines, limit or WINDOW_TOKENS)


def _first_id(line: str) -> int | None:
    try:
        return int(line[1:line.index("]")])
    except ValueError:
        return None


def parse(raw, ids: list[int]) -> list[dict]:
    """Model answer -> [{"line", "title", "summary"}] with every line a real segment id inside `ids`
    (a cited id that does not exist moves to the nearest one that does); sorted, one chapter per line."""
    if not ids or not isinstance(raw, dict):
        return []
    srt = sorted(ids)
    out: dict[int, dict] = {}
    for c in raw.get("chapters") or []:
        if not isinstance(c, dict):
            continue
        title = str(c.get("title") or "").strip().strip('"').strip()
        if not title:
            continue
        try:
            ln = int(c.get("line"))
        except (TypeError, ValueError):
            continue
        if ln not in set(srt):
            k = bisect.bisect_left(srt, ln)
            near = [srt[j] for j in (k - 1, k) if 0 <= j < len(srt)]
            ln = min(near, key=lambda x: abs(x - ln))
        if ln not in out:
            out[ln] = {"line": ln, "title": title[:80], "summary": str(c.get("summary") or "").strip()}
    return [out[k] for k in sorted(out)]


def _same(a: dict, b: dict) -> bool:
    from . import analysis as A

    wa, wb = A._words(a["title"]), A._words(b["title"])
    if not wa or not wb:
        return A._norm(a["title"]) == A._norm(b["title"])
    return len(wa & wb) / len(wa | wb) >= 0.7  # "Surum tarihi" and "Surum kapsami" are different chapters


def assemble(found: list[dict], segments: list[dict], max_n: int | None = None) -> list[dict]:
    """Chapters from all windows -> final list with start / end seconds. Neighbours with the same title are
    merged, a chapter shorter than MIN_CHAPTER_SECONDS is folded into the one before it (the first into the
    one after it), the first chapter starts with the recording, at most `max_n` chapters stay."""
    from . import analysis as A

    if not segments:
        return []
    by_id = {s["id"]: s for s in segments}
    t0, t1 = min(s["start"] for s in segments), max(s["end"] for s in segments)
    max_n = max_chapters(t1 - t0) if max_n is None else max_n
    if max_n <= 0:
        return []
    ch = [dict(c, start=by_id[c["line"]]["start"]) for c in sorted(found, key=lambda c: by_id[c["line"]]["start"])
          if c.get("line") in by_id]
    if not ch:
        return []
    ch[0]["start"] = t0  # the first chapter covers the beginning too
    ch[0]["line"] = min(segments, key=lambda s: s["start"])["id"]

    def merge_into(i: int, j: int) -> None:  # chapter j disappears into chapter i
        keep, gone = ch[i], ch.pop(j)
        if gone["summary"] and A._norm(gone["summary"]) not in A._norm(keep["summary"]):
            keep["summary"] = (keep["summary"] + " " + gone["summary"]).strip()

    i = 1
    while i < len(ch):  # same topic said twice in a row
        if _same(ch[i - 1], ch[i]):
            merge_into(i - 1, i)
        else:
            i += 1

    def length(i: int) -> float:
        return (ch[i + 1]["start"] if i + 1 < len(ch) else t1) - ch[i]["start"]

    while len(ch) > 1:
        shorts = [i for i in range(len(ch)) if length(i) < MIN_CHAPTER_SECONDS]
        short = min(shorts, key=length) if shorts else None  # the shortest first: it may be what makes its neighbour long enough
        if short is None and len(ch) <= max_n:
            break
        if short is None:  # too many: fold the shortest one
            short = min(range(len(ch)), key=length)
        if short == 0:
            ch[1]["start"], ch[1]["line"] = ch[0]["start"], ch[0]["line"]
            ch.pop(0)
        else:
            merge_into(short - 1, short)
    for i, c in enumerate(ch):
        c["end"] = ch[i + 1]["start"] if i + 1 < len(ch) else t1
    return ch


def clean_texts(chs: list[dict], known: set[str]) -> list[dict]:
    """Sentences with an invented number (a version, an amount) are cut from the summary, as in analysis."""
    from . import analysis as A

    out = []
    for c in chs:
        if not A._grounded(c["title"], known):
            continue
        out.append({**c, "summary": A._drop_ungrounded(c["summary"], known)})
    return out


def build(segments: list[dict], lines: list[str], lang: str, call, on_window=None) -> list[dict]:
    """Run the model over the transcript in windows. `call(prompt, schema, max_tokens=...)` is the
    analysis' bound generate function. Raises whatever `call` raises; the caller decides (soft failure)."""
    if not segments:
        return []
    t0, t1 = min(s["start"] for s in segments), max(s["end"] for s in segments)
    cap = max_chapters(t1 - t0)
    if cap <= 0:
        return []
    from . import analysis as A

    wins = windows(lines)
    found: list[dict] = []
    prev = ""
    by_id = {s["id"]: s for s in segments}
    for k, win in enumerate(wins):
        ids = [i for i in (_first_id(x) for x in win) if i is not None]
        if not ids:
            continue
        span = by_id[ids[-1]]["end"] - by_id[ids[0]]["start"]
        n = max(1, min(8, cap if len(wins) == 1 else int(span // SECONDS_PER_CHAPTER) or 1))
        prompt = PROMPT[lang].format(max=n, transcript="\n".join(win),
                                     previous=PREVIOUS[lang].format(title=prev) if prev else "")
        got = parse(call(prompt, schema(n), max_tokens=900), ids)
        if got:
            found += got
            prev = got[-1]["title"]
        if on_window:
            on_window(k + 1, len(wins))
    known = A._numbers(" ".join(A._text(s) for s in segments)) | {f"{(t1 - t0) / 60:.1f}"}
    return clean_texts(assemble(found, segments, cap), known)
