"""Local search database for the AI assistant: %APPDATA%\\SesDefteri\\sohbet.db (SQLite, full-text search).

The recordings (jobs/*/transcript.json, analysis.json) stay the source of truth; this file is only an index and is
rebuilt when it is deleted. It holds every transcript line and the analysis items (summary, decisions, tasks, open
questions) with the recording's date, so the assistant can ask "what did Ahmet say about the app last week" as one
query: date range + speaker + words.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

from . import export, store

KINDS = ("line", "summary", "decision", "task", "question")
_FOLD = str.maketrans("ıİIçÇğĞöÖşŞüÜâÂîÎûÛ", "iiiccggoossuuaaiiuu")
_lock = threading.RLock()


def fold(s: str) -> str:
    """Lower case without Turkish letters: 'Ahmet'in UYGULAMAYI' -> "ahmet'in uygulamayi"."""
    return (s or "").translate(_FOLD).lower()


def db_path() -> Path:
    return store.data_dir() / "sohbet.db"


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(db_path(), check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, filename TEXT, created REAL, duration REAL, mtime REAL);
        CREATE TABLE IF NOT EXISTS items(rowid INTEGER PRIMARY KEY, job_id TEXT, kind TEXT, seg INTEGER, start REAL,
                                         speaker TEXT, text TEXT);
        CREATE INDEX IF NOT EXISTS items_job ON items(job_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2');
    """)
    return c


# ---------------------------------------------------------------- keeping it up to date
def _job_items(job: dict, analysis: dict | None) -> list[tuple]:
    """(kind, seg, start, speaker, text) for one recording."""
    lang = "tr"
    segs = {s["id"]: s for s in job.get("segments") or []}
    out = []
    for s in job.get("segments") or []:
        text = (s.get("text_edited") or "").strip()
        if text:
            out.append(("line", s["id"], s["start"], export._name(job, s["speaker"], lang), text))
    a = analysis or {}

    def at(item):
        seg = segs.get(item.get("line"))
        return (seg["id"], seg["start"]) if seg else (None, None)
    if a.get("summary"):
        out.append(("summary", None, 0.0, "", str(a["summary"])))
    for d in a.get("decisions") or []:
        out.append(("decision", *at(d), "", str(d.get("text", ""))))
    for t in a.get("tasks") or []:
        who = export._spk(job, t.get("owner"), lang)
        due = f" ({t['due']})" if t.get("due") else ""
        out.append(("task", *at(t), "" if who == "—" else who, f"{t.get('task', '')}{due}"))
    for q in a.get("open_questions") or []:
        who = export._spk(job, q.get("asker"), lang)
        out.append(("question", *at(q), "" if who == "—" else who, str(q.get("text", ""))))
    return out


def _mtime(job_dir: Path) -> float:
    return max((f.stat().st_mtime for f in (job_dir / "transcript.json", job_dir / "analysis.json") if f.exists()),
               default=0.0)


def sync() -> int:
    """Index new or changed finished recordings, drop deleted ones. Returns how many were (re)indexed."""
    with _lock:
        c = connect()
        try:
            known = {r[0]: r[1] for r in c.execute("SELECT id, mtime FROM jobs")}
            seen, changed = set(), 0
            for d in store.jobs_dir().iterdir() if store.jobs_dir().exists() else []:
                f = d / "transcript.json"
                if not f.exists():
                    continue
                mt = _mtime(d)
                if known.get(d.name) == mt:
                    seen.add(d.name)
                    continue
                try:
                    job = json.loads(f.read_text("utf-8"))
                except (OSError, ValueError):
                    continue
                if job.get("status") != "done":
                    continue
                seen.add(d.name)
                analysis = None
                if (d / "analysis.json").exists():
                    try:
                        analysis = json.loads((d / "analysis.json").read_text("utf-8"))
                    except (OSError, ValueError):
                        pass
                _remove(c, d.name)
                c.execute("INSERT INTO jobs VALUES (?,?,?,?,?)",
                          (d.name, job.get("filename", ""), float(job.get("created") or 0), float(job.get("duration") or 0), mt))
                for kind, seg, start, spk, text in _job_items(job, analysis):
                    cur = c.execute("INSERT INTO items(job_id, kind, seg, start, speaker, text) VALUES (?,?,?,?,?,?)",
                                    (d.name, kind, seg, start, spk, text))
                    c.execute("INSERT INTO items_fts(rowid, body) VALUES (?, ?)", (cur.lastrowid, fold(f"{spk} {text}")))
                changed += 1
            for gone in set(known) - seen:
                _remove(c, gone)
            c.commit()
            return changed
        finally:
            c.close()


def _remove(c: sqlite3.Connection, job_id: str) -> None:
    c.execute("DELETE FROM items_fts WHERE rowid IN (SELECT rowid FROM items WHERE job_id=?)", (job_id,))
    c.execute("DELETE FROM items WHERE job_id=?", (job_id,))
    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


# ---------------------------------------------------------------- queries
# common Turkish endings (letters folded), longest first; stripping them gives a prefix for "word*" search
_SUFFIXES = sorted({"daki", "deki", "taki", "teki", "lari", "leri", "larin", "lerin", "nin", "nun", "dan", "den", "tan",
                    "ten", "lar", "ler", "yla", "yle", "da", "de", "ta", "te", "ya", "ye", "yi", "yu", "in", "un", "la",
                    "le", "si", "su", "ki", "i", "u", "a", "e"}, key=len, reverse=True)


def stem(word: str) -> str:
    """Rough Turkish stem for prefix search: 'uygulamayı' -> 'uygulam', 'toplantıdaki' -> 'toplant', "Ahmet'in" -> 'ahmet'."""
    w = re.sub(r"[^0-9a-z]", "", fold(word.split("'")[0] if "'" in word else word))
    for _ in range(3):
        suf = next((s for s in _SUFFIXES if w.endswith(s) and len(w) - len(s) >= 4), None)
        if not suf:
            break
        w = w[: -len(suf)]
    return w


def match_query(words: list[str]) -> str:
    stems = sorted({stem(w) for w in words if len(stem(w)) >= 3})
    return " OR ".join(f'"{s}"*' for s in stems)


def people_in(speaker_names: list[str]) -> list[str]:
    """The speaker labels in the database that match the given names (case and Turkish letters ignored,
    'Ahmet' also matches 'Ahmet Yılmaz')."""
    wanted = [fold(n).strip() for n in speaker_names if n and n.strip()]
    if not wanted:
        return []
    with _lock:
        c = connect()
        try:
            labels = [r[0] for r in c.execute("SELECT DISTINCT speaker FROM items WHERE speaker != ''")]
        finally:
            c.close()
    out = []
    for lab in labels:
        f = fold(lab)
        if any(w == f or f.startswith(w + " ") or w.startswith(f + " ") for w in wanted):
            out.append(lab)
    return out


def search(words: list[str] | None = None, date_from: float | None = None, date_to: float | None = None,
           speakers: list[str] | None = None, kinds: list[str] | None = None, limit: int = 25) -> list[dict]:
    """Items matching all given filters; with words ranked by full-text relevance, otherwise newest first."""
    q = match_query(words or [])
    where, args = [], []
    if date_from is not None:
        where.append("j.created >= ?"); args.append(date_from)
    if date_to is not None:
        where.append("j.created < ?"); args.append(date_to)
    if speakers:
        where.append(f"i.speaker IN ({','.join('?' * len(speakers))})"); args += speakers
    if kinds:
        where.append(f"i.kind IN ({','.join('?' * len(kinds))})"); args += kinds
    sql = ("SELECT i.rowid, i.job_id, i.kind, i.seg, i.start, i.speaker, i.text, j.filename, j.created "
           "FROM items i JOIN jobs j ON j.id = i.job_id")
    if q:
        sql += " JOIN items_fts f ON f.rowid = i.rowid"
        where.insert(0, "items_fts MATCH ?"); args.insert(0, q)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + ("bm25(items_fts), j.created DESC" if q else "j.created DESC, i.start") + " LIMIT ?"
    args.append(limit)
    with _lock:
        c = connect()
        try:
            rows = c.execute(sql, args).fetchall()
        finally:
            c.close()
    keys = ("rowid", "job_id", "kind", "seg", "start", "speaker", "text", "filename", "created")
    return [dict(zip(keys, r)) for r in rows]


def line_at(job_id: str, seg: int, date_from=None, date_to=None, speakers=None) -> dict | None:
    """One transcript line, only if it passes the same filters as search()."""
    where, args = ["i.job_id=?", "i.seg=?", "i.kind='line'"], [job_id, seg]
    if date_from is not None:
        where.append("j.created >= ?"); args.append(date_from)
    if date_to is not None:
        where.append("j.created < ?"); args.append(date_to)
    if speakers:
        where.append(f"i.speaker IN ({','.join('?' * len(speakers))})"); args += speakers
    with _lock:
        c = connect()
        try:
            r = c.execute("SELECT i.rowid, i.job_id, i.kind, i.seg, i.start, i.speaker, i.text, j.filename, j.created "
                          "FROM items i JOIN jobs j ON j.id = i.job_id WHERE " + " AND ".join(where), args).fetchone()
        finally:
            c.close()
    keys = ("rowid", "job_id", "kind", "seg", "start", "speaker", "text", "filename", "created")
    return dict(zip(keys, r)) if r else None


def context(job_id: str, seg: int, around: int = 1) -> list[dict]:
    """The lines just before and after a line (to give the assistant the whole thought)."""
    with _lock:
        c = connect()
        try:
            rows = c.execute("SELECT seg, start, speaker, text FROM items WHERE job_id=? AND kind='line' "
                             "AND seg BETWEEN ? AND ? ORDER BY seg", (job_id, seg - around, seg + around)).fetchall()
        finally:
            c.close()
    return [{"seg": r[0], "start": r[1], "speaker": r[2], "text": r[3]} for r in rows]


def recording_dates(date_from: float | None = None, date_to: float | None = None, near: float | None = None,
                    limit: int = 3) -> list[float]:
    """Start times of recordings in a range; with `near`, the ones closest to that moment."""
    with _lock:
        c = connect()
        try:
            if near is not None:
                q = "SELECT created FROM jobs ORDER BY ABS(created - ?) LIMIT ?"
                return [r[0] for r in c.execute(q, (near, limit))]
            q = "SELECT created FROM jobs WHERE created >= ? AND created < ? ORDER BY created LIMIT ?"
            return [r[0] for r in c.execute(q, (date_from or 0, date_to or 1e12, limit))]
        finally:
            c.close()


def counts() -> dict:
    with _lock:
        c = connect()
        try:
            return {"recordings": c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                    "items": c.execute("SELECT COUNT(*) FROM items").fetchone()[0]}
        finally:
            c.close()
