"""Saved assistant conversations: a list on the side, like ChatGPT.

The page keeps the open conversation in memory; after every answer it sends the whole thing here
(msgs = what is shown, history = what the model is told about the previous questions). The dicts
are opaque to this module: it only reads/writes them, never looks inside. Everything lives in one
JSON file, written atomically; a corrupt or missing file means "no conversations yet", never a crash.
"""
from __future__ import annotations

import functools
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

_lock = threading.RLock()  # read-modify-write: no other thread may write between the read and the write

MAX_CHATS = 200  # the oldest-updated conversation is dropped first
MAX_MSGS = 400  # per conversation: the newest messages are kept
TITLE_MAX = 48
NAME_MAX = 80


def _locked(fn):
    @functools.wraps(fn)
    def inner(*a, **kw):
        with _lock:
            return fn(*a, **kw)
    return inner


def _path() -> Path:
    from . import store

    return store.data_dir() / "chats.json"


def _load() -> list[dict]:
    """The whole file, or [] when it is missing or damaged (the conversations are a bonus, not a must)."""
    try:
        data = json.loads(_path().read_text("utf-8"))
        return [c for c in data if isinstance(c, dict) and isinstance(c.get("id"), str)] if isinstance(data, list) else []
    except Exception:
        return []


def _write(chats: list[dict]) -> None:
    p = _path()
    tmp = p.with_name(f"chats.{uuid.uuid4().hex[:8]}.tmp")  # never shared between writers
    try:
        tmp.write_text(json.dumps(chats, ensure_ascii=False, indent=1), "utf-8")
        for attempt in range(10):  # Windows: a reader holding the file open makes replace fail for a moment
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.02)
    finally:
        tmp.unlink(missing_ok=True)


def _summary(c: dict) -> dict:
    return {"id": c["id"], "title": c.get("title") or "", "updated": c.get("updated") or 0.0,
            "count": len(c.get("msgs") or [])}


def _trim(chats: list[dict]) -> list[dict]:
    if len(chats) > MAX_CHATS:  # newest updated first, the oldest-updated ones fall off the end
        chats = sorted(chats, key=lambda c: c.get("updated") or 0.0, reverse=True)[:MAX_CHATS]
    return chats


def fallback_title(question: str) -> str:
    """The first few words of the question, until the model comes up with a better title."""
    words = re.sub(r"\s+", " ", (question or "").strip()).split(" ")[:6]
    title = " ".join(words).strip()[:TITLE_MAX].rstrip(" .,!?…:;\"'”’)]}")
    return title.strip() or "Yeni sohbet"


def list_chats() -> list[dict]:
    """[{"id", "title", "updated", "count"}] for the side list, the newest updated first (no msgs)."""
    with _lock:
        return [_summary(c) for c in sorted(_load(), key=lambda c: c.get("updated") or 0.0, reverse=True)]


def get(chat_id: str) -> dict | None:
    with _lock:
        return next((c for c in _load() if c.get("id") == chat_id), None)


@_locked
def save(chat_id: str | None, msgs: list, history: list, title_hint: str = "") -> dict:
    """Create a conversation (unknown or missing id) or replace the messages of an existing one.
    Returns the summary of the saved conversation."""
    chats = _load()
    now = time.time()
    chat = next((c for c in chats if c.get("id") == chat_id), None) if chat_id else None
    msgs, history = list(msgs or [])[-MAX_MSGS:], list(history or [])
    if chat is None:
        chat = {"id": uuid.uuid4().hex[:8], "title": fallback_title(title_hint), "auto_title": True,
                "created": now, "updated": now, "msgs": msgs, "history": history}
        chats.append(chat)
    else:
        chat.update(msgs=msgs, history=history, updated=now)
    _write(_trim(chats))
    return _summary(chat)


@_locked
def rename(chat_id: str, title: str) -> dict | None:
    """The user named it: no model may change the title again. An empty name changes nothing."""
    chats = _load()
    chat = next((c for c in chats if c.get("id") == chat_id), None)
    if chat is None:
        return None
    title = (title or "").strip()[:NAME_MAX]
    if title:
        chat.update(title=title, auto_title=False)
        _write(chats)
    return _summary(chat)


def delete(chat_id: str) -> bool:
    with _lock:
        chats = _load()
        rest = [c for c in chats if c.get("id") != chat_id]
        if len(rest) == len(chats):
            return False
        _write(rest)
        return True


@_locked
def set_auto_title(chat_id: str, title: str) -> dict | None:
    """The model's title for a conversation nobody has named yet; a manual rename wins."""
    chats = _load()
    chat = next((c for c in chats if c.get("id") == chat_id), None)
    if chat is None or not chat.get("auto_title"):
        return None
    title = (title or "").strip()[:TITLE_MAX]
    if title:
        chat.update(title=title)  # only the name changes: the conversation keeps its place in the list
        _write(chats)
    return _summary(chat)
