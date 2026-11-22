"""What the assistant can DO (not only answer): add a person from the recordings, open a recording,
name a speaker. Everything here only prepares or executes what the user already confirmed with a click.

find_speaker_groups("Ece") looks at every finished recording for a speaker labelled Ece, makes a voice
print for each and groups the alike ones, so "Ece" in two meetings can be added as one person (or the
user sees that the name was given to two different voices). It decodes audio, so it can take seconds;
nothing is cached.
"""
from __future__ import annotations

import datetime as dt
import re

import numpy as np

from . import chat, chatdb, people, store

MIN_PRINT_SPEECH = 4.0   # a speaker needs at least this much speech for a voice print
MAX_MATCHES = 5


def _name_matches(label: str, name: str) -> bool:
    """Case and Turkish-letter insensitive; 'Ece Hanım' counts as Ece, 'Ahmet Yılmaz' as Ahmet."""
    n = chatdb.fold(name or "").strip()
    if not n:
        return False
    f = chatdb.fold(label or "").strip()
    return f == n or n in chatdb.fold(f).split()


def speaker_print(job_id: str, speaker: int) -> np.ndarray | None:
    """Voice print of one speaker of a finished recording (None when there is too little speech).
    Same procedure as people.learn_from_job; a separate function so tests can replace it."""
    from . import audio
    from .chunking import speech_regions

    job = store.read_transcript(job_id)
    segs = job.get("segments") or []
    if not any(s["speaker"] == int(speaker) for s in segs):
        return None
    samples, _ = audio.decode(store.job_path(job_id) / "audio.mp3")
    regions = speech_regions(samples)
    speech = people._speaker_speech(samples, segs, int(speaker), regions)
    if len(speech) / people.SR < MIN_PRINT_SPEECH:
        return None
    E = people.window_embeddings(speech, people.MAX_JOB_SPEECH)
    return people._unit(E.sum(0)) if len(E) else None


def _known_people() -> list[dict]:
    return [p for p in people._all() if p.get("embedding")]


def _best_person(v: np.ndarray, known: list[dict]) -> dict | None:
    """The person this voice print is most alike, when it is alike enough to suggest."""
    best = None
    for p in known:
        sc = float(v @ people._unit(np.array(p["embedding"], np.float32)))
        if best is None or sc > best[2]:
            best = (p["id"], p["name"], sc)
    return {"id": best[0], "name": best[1], "score": round(best[2], 3)} \
        if best and best[2] >= people.SUGGEST else None


def find_speaker_groups(name: str) -> dict:
    """{"name", "groups": [{"items": [{"job_id","title","speaker","seconds","sample_start"}],
    "person": {"id","name","score"}|None}], "skipped": n}."""
    name = (name or "").strip()
    found: list[dict] = []
    skipped = 0
    for j in store.list_jobs():
        if j.get("status") != "done":
            continue
        try:
            job = store.read_transcript(j["id"])
        except (OSError, ValueError):
            continue
        segs = job.get("segments") or []
        for k, label in (job.get("speakers") or {}).items():
            try:
                spk = int(k)
            except (TypeError, ValueError):
                continue
            mine = [s for s in segs if s["speaker"] == spk]
            if not mine or not _name_matches(str(label), name):
                continue
            try:
                v = speaker_print(j["id"], spk)
            except Exception:  # a broken recording must not stop the others
                v = None
            if v is None:
                skipped += 1
                continue
            longest = max(mine, key=lambda s: s["end"] - s["start"])
            found.append({"job_id": j["id"], "title": j.get("filename") or j["id"], "speaker": spk,
                          "seconds": round(sum(s["end"] - s["start"] for s in mine), 1),
                          "sample_start": longest["start"], "_v": v})

    thr = getattr(people, "MATCH", 0.6)
    groups: list[dict] = []
    for it in found:  # greedy: the first print opens a group, the alike ones join it
        v = it.pop("_v")
        for g in groups:
            if float(v @ g["_c"]) >= thr:
                g["items"].append(it)
                g["_c"] = people._unit(g["_c"] + v)
                break
        else:
            groups.append({"items": [it], "_c": v})
    known = _known_people()
    out = []
    for g in sorted(groups, key=lambda g: -len(g["items"])):
        out.append({"items": g["items"], "person": _best_person(g["_c"], known)})
    return {"name": name, "groups": out, "skipped": skipped}


def add_group(name: str, items: list[dict], person_id: str | None = None) -> dict:
    """Make every item ({"job_id", "speaker"}) a voice sample of ONE person: the given person, or a new
    one called `name` that the first item creates. Returns that person."""
    name = (name or "").strip()
    if not items:
        raise ValueError("no items")
    person = None
    for it in items:
        person = people.add_sample_from_job(str(it.get("job_id") or ""), int(it.get("speaker") or 0),
                                            person_id or (person or {}).get("id"), name)
        person_id = person_id or person["id"]
    return person


def find_recording(words: str, now: dt.datetime | None = None) -> list[dict]:
    """Recordings that these words identify: 'son'/'last' = the newest, a date, or title/text words.
    At most MAX_MATCHES, newest first."""
    now = now or dt.datetime.now()
    w = chatdb.fold(words or "").strip()
    done = [j for j in store.list_jobs() if j.get("status") == "done"]

    def out(jobs: list[dict]) -> list[dict]:
        return [{"id": j["id"], "title": j.get("filename") or j["id"], "created": j.get("created")}
                for j in sorted(jobs, key=lambda j: j.get("created") or 0, reverse=True)[:MAX_MATCHES]]

    if not done:
        return []
    if not w or re.search(r"\b(son|sonki|last|latest|en son)\b", w):
        return out([max(done, key=lambda j: j.get("created") or 0)])
    when = chat.resolve_dates(words, now)
    if when:
        return out([j for j in done if when[0] <= (j.get("created") or 0) < when[1]])
    # title words first (folded here: store's own fold keeps ü/ö), then any word of the text
    words = [x for x in w.split() if len(x) >= 3]
    hits = [j for j in done if any(x in chatdb.fold(j.get("filename") or "") for x in words)]
    if not hits and words:
        hits = [j for j in store.list_jobs(" ".join(words)) if j.get("status") == "done"]
    return out(hits)


def name_speaker(job_id: str, speaker: int, name: str) -> dict:
    """Give a speaker of a recording a name (the label the transcript shows)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("empty name")
    return store.save_edits(job_id, None, {int(speaker): name[:80]})
