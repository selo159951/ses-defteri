"""Search by meaning across all recordings, fully offline.

A small multilingual embedding model (ONNX, int8, runs on the CPU through onnxruntime) turns passages of the
transcripts and the search question into vectors. Each recording gets two files next to its transcript:

    jobs/<id>/embeddings.npy    float16 matrix, one row per passage
    jobs/<id>/embeddings.json   which model, the transcript's mtime, and per passage: first line id, start, line ids, text

Passages are windows of a few consecutive lines. A background worker keeps the files up to date (new recordings,
edits, old recordings built lazily); it only works while no transcription is running. Searching is one
matrix product over all passages, mixed with a keyword score (exact phrase first).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from . import models, store

# The model is downloaded once from Hugging Face like the speech and analysis models; after that nothing leaves the PC.
MODEL = {
    "name": "multilingual-e5-base",
    "label": "Multilingual E5 base (int8)",
    "repo": "Xenova/multilingual-e5-base",
    "files": {"model.onnx": "onnx/model_int8.onnx", "tokenizer.json": "tokenizer.json"},
    "size": 278_184_162 + 17_082_660,
    "query_prefix": "query: ",
    "passage_prefix": "passage: ",
}
INDEX_VERSION = 1
MAX_TOKENS = 256
WINDOW_CHARS = 200  # a passage grows by whole lines until it has this many characters ...
WINDOW_LINES = 4  # ... or this many lines
POLL_SECONDS = 15
SETTLE_SECONDS = 4  # a transcript edited just now is indexed a moment later (typing in the editor)

# ---- scoring (calibrated with multilingual-e5-base on tests/data/search_meetings.py) ----
LEX_WEIGHT = 0.12  # keyword share of the mixed score
PHRASE_BONUS = 0.10  # the whole question appears literally
MARGIN = 0.03  # keep results within this distance of the best score ...
FLOOR = 0.775  # ... and only if the meaning score itself is at least this (e5 scores are squeezed into ~0.7-0.85: relevant tops 0.77-0.85, unrelated questions 0.74-0.81)


# ---------------- model files ----------------
def model_dir() -> Path:
    return models.root() / "embed" / MODEL["name"]


def is_downloaded() -> bool:
    d = model_dir()
    return all((d / f).is_file() and (d / f).stat().st_size > 1000 for f in MODEL["files"])


_dl: dict = {"running": False, "done": 0, "total": MODEL["size"], "error": None}
_dl_lock = threading.Lock()


def download_status() -> dict:
    with _dl_lock:
        return dict(_dl)


def start_download() -> dict:
    with _dl_lock:
        if _dl["running"]:
            return dict(_dl)
        _dl.update(running=True, done=0, total=MODEL["size"], error=None)
    threading.Thread(target=_download, daemon=True).start()
    return download_status()


def _download() -> None:
    d = model_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        base = 0
        for dest_name, remote in MODEL["files"].items():
            dest = d / dest_name
            if dest.is_file() and dest.stat().st_size > 1000:
                base += dest.stat().st_size
                with _dl_lock:
                    _dl["done"] = base
                continue
            part = dest.with_name(dest.name + ".part")
            req = urllib.request.Request(f"https://huggingface.co/{MODEL['repo']}/resolve/main/{remote}",
                                         headers={"User-Agent": "SesDefteri"})
            got = 0
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    with _dl_lock:
                        _dl["done"] = base + got
            length = int(r.headers.get("Content-Length") or 0)
            if length and got != length:
                raise RuntimeError(f"incomplete download ({got}/{length} bytes)")
            os.replace(part, dest)
            base += got
        with _dl_lock:
            _dl.update(running=False, done=_dl["total"])
        kick()
    except Exception as e:
        with _dl_lock:
            _dl.update(running=False, error=f"{type(e).__name__}: {e}")


# ---------------- embedder ----------------
class Embedder:
    """onnxruntime + tokenizers. embed() returns L2-normalised float32 vectors."""

    def __init__(self, directory: Path | None = None, threads: int = 2, model_file: str = "model.onnx"):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = directory or model_dir()
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_padding()
        self.tok.enable_truncation(MAX_TOKENS)
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(str(d / model_file), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def embed(self, texts: list[str], batch: int = 16, should_stop=None) -> np.ndarray:
        out = None
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # similar lengths together: less padding
        for a in range(0, len(order), batch):
            if should_stop and should_stop():
                raise InterruptedError
            idx = order[a:a + batch]
            enc = self.tok.encode_batch([texts[i] for i in idx])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            h = self.sess.run(None, feed)[0]
            v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            if out is None:
                out = np.zeros((len(texts), v.shape[1]), dtype=np.float32)
            out[idx] = v / np.linalg.norm(v, axis=1, keepdims=True)
        return out if out is not None else np.zeros((0, 384), dtype=np.float32)


_embedder = None
_embedder_lock = threading.Lock()


def get_embedder():
    """The shared embedder (tests replace it with set_embedder)."""
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            _embedder = Embedder()
        return _embedder


def set_embedder(e) -> None:
    global _embedder
    _embedder = e


def ready() -> bool:
    return _embedder is not None or is_downloaded()


# ---------------- text helpers ----------------
def fold(s: str) -> str:
    return store._fold(s)


_WORD = re.compile(r"\w+", re.U)
_STOP = {"ne", "ve", "bir", "bu", "şu", "o", "mi", "mı", "mu", "mü", "de", "da", "ki", "için", "ile", "ama", "gibi",
         "the", "and", "was", "when", "what", "did", "we", "talk", "about"}


def _stems(q: str) -> list[str]:
    """Crude Turkish-friendly stems: the first 5 letters of every meaningful word (suffixes come after them)."""
    out = []
    for w in _WORD.findall(fold(q)):
        if len(w) >= 3 and w not in _STOP:
            out.append(w[:5])
    return list(dict.fromkeys(out))


def lex_prepare(q: str):
    """(compiled word-start patterns of the question's stems, folded whole question) - made once per search."""
    return [re.compile(r"" + re.escape(s)) for s in _stems(q)], fold(q.strip())


def lexical(prep, folded_text: str) -> tuple[float, bool]:
    """(share of the question's words found in the text, whole question appears literally). Text is pre-folded."""
    pats, fq = prep
    share = (sum(1 for p in pats if p.search(folded_text)) / len(pats)) if pats else 0.0
    return share, bool(fq) and fq in folded_text


# ---------------- passages ----------------
def make_windows(segments: list[dict]) -> list[dict]:
    """Group consecutive lines into passages: {"seg": first line id, "segs": [ids], "start": s, "text": str}."""
    wins, cur, chars = [], [], 0
    for s in segments:
        t = (s.get("text_edited") or "").strip()
        if not t:
            continue
        cur.append((s, t))
        chars += len(t)
        if chars >= WINDOW_CHARS or len(cur) >= WINDOW_LINES:
            wins.append(cur)
            cur, chars = [], 0
    if cur:
        wins.append(cur)
    return [{"seg": w[0][0]["id"], "segs": [s["id"] for s, _ in w], "start": w[0][0]["start"],
             "text": " ".join(t for _, t in w)} for w in wins]


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ---------------- per recording index ----------------
def _files(job_id: str) -> tuple[Path, Path]:
    d = store.job_path(job_id)
    return d / "embeddings.json", d / "embeddings.npy"


def _transcript_mtime(job_id: str) -> int:
    return (store.job_path(job_id) / "transcript.json").stat().st_mtime_ns


def read_meta(job_id: str) -> dict | None:
    try:
        meta = json.loads(_files(job_id)[0].read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if meta.get("version") != INDEX_VERSION or meta.get("model") != MODEL["name"]:
        return None
    return meta


def is_fresh(job_id: str) -> bool:
    hit = _load(job_id)  # cached: no file is parsed again while it is unchanged
    try:
        return bool(hit) and hit[1].get("mtime") == _transcript_mtime(job_id)
    except OSError:
        return False


def _write_index(job_id: str, meta: dict, mat: np.ndarray | None) -> None:
    jp, npy = _files(job_id)
    if mat is not None:
        tmp = npy.with_name("embeddings.tmp.npy")
        np.save(tmp, mat.astype(np.float16))
        os.replace(tmp, npy)
    tmp = jp.with_name("embeddings.json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    os.replace(tmp, jp)


def index_job(job_id: str, embedder=None, should_stop=None) -> str:
    """Bring one recording's index up to date. Returns "built" | "updated" | "fresh" | "skipped".
    Passages whose text did not change keep their vector."""
    embedder = embedder or get_embedder()
    try:
        mt = _transcript_mtime(job_id)
        data = store.read_transcript(job_id)
    except (OSError, ValueError):
        return "skipped"
    if data.get("status") != "done" or not data.get("segments"):
        return "skipped"
    wins = make_windows(data["segments"])
    if not wins:  # only empty lines
        return "skipped"
    old = read_meta(job_id)
    old_rows: dict[str, int] = {}
    old_mat = None
    if old:
        try:
            old_mat = np.load(_files(job_id)[1])
            old_rows = {w["h"]: i for i, w in enumerate(old["windows"])}
        except (OSError, ValueError):
            old_rows = {}
    for w in wins:
        w["h"] = _h(w["text"])
    if old and [(w["h"], w["start"], w["segs"]) for w in wins] == \
            [(w["h"], w["start"], w["segs"]) for w in old["windows"]]:
        if old.get("mtime") == mt:
            return "fresh"
        old["mtime"] = mt  # touched without a text change (rename, analysis, speaker labels)
        _write_index(job_id, old, None)
        return "fresh"
    need = [i for i, w in enumerate(wins) if w["h"] not in old_rows]
    vecs = None
    if need:
        vecs = embedder.embed([MODEL["passage_prefix"] + wins[i]["text"] for i in need], should_stop=should_stop)
    mat = np.zeros((len(wins), (vecs if vecs is not None else old_mat).shape[1]), dtype=np.float32)
    for i, w in enumerate(wins):
        if w["h"] in old_rows and old_mat is not None:
            mat[i] = old_mat[old_rows[w["h"]]]
    if need:
        for k, i in enumerate(need):
            mat[i] = vecs[k]
    meta = {"version": INDEX_VERSION, "model": MODEL["name"], "mtime": mt,
            "windows": [{k: w[k] for k in ("h", "seg", "segs", "start", "text")} for w in wins]}
    _write_index(job_id, meta, mat)
    return "updated" if old else "built"


def remove_index(job_id: str) -> None:
    for f in _files(job_id):
        f.unlink(missing_ok=True)
    _cache.pop(job_id, None)


# ---------------- in-memory corpus ----------------
_cache: dict[str, tuple] = {}  # job id -> (stamp, meta, float16 matrix, folded texts)
_cache_lock = threading.Lock()


def _load(job_id: str):
    jp, npy = _files(job_id)
    try:
        stamp = (jp.stat().st_mtime_ns, npy.stat().st_mtime_ns)
    except OSError:
        _cache.pop(job_id, None)
        return None
    hit = _cache.get(job_id)
    if hit and hit[0] == stamp:
        return hit
    meta = read_meta(job_id)
    if not meta:
        return None
    try:
        mat = np.load(npy)  # float16 in memory; converted per search
    except (OSError, ValueError):
        return None
    if len(mat) != len(meta["windows"]):
        return None
    folded = [fold(w["text"]) for w in meta["windows"]]
    _cache[job_id] = hit = (stamp, meta, mat, folded)
    return hit


def _job_ids() -> list[str]:
    return [p.name for p in store.jobs_dir().iterdir() if (p / "transcript.json").exists()]


def coverage() -> dict:
    ids = _job_ids()
    done = 0
    for j in ids:
        if is_fresh(j):
            done += 1
    return {"indexed": done, "total": len(ids)}


# ---------------- search ----------------
def search(q: str, limit: int = 30, per_job: int = 5, embedder=None) -> dict:
    """{"ready": bool, "results": [...], "indexed": n, "total": n}. Result: job_id, filename, seg, start, speaker,
    text, score, exact. Recordings that are not indexed yet are searched by keyword only."""
    q = (q or "").strip()
    cov = coverage()
    out = {"ready": ready(), "indexing": bool(_state.get("job")), **cov, "results": []}
    if not q or not out["ready"]:
        return out
    embedder = embedder or get_embedder()
    qv = embedder.embed([MODEL["query_prefix"] + q])[0]
    prep = lex_prepare(q)
    rows = []  # (score, cos, exact, job_id, window)
    with _cache_lock:
        for job_id in _job_ids():
            hit = _load(job_id)
            if not hit:
                continue
            _, meta, mat, folded = hit
            cos = mat.astype(np.float32) @ qv
            for i, w in enumerate(meta["windows"]):
                share, exact = lexical(prep, folded[i])
                rows.append((float(cos[i]) + LEX_WEIGHT * share + (PHRASE_BONUS if exact else 0.0),
                             float(cos[i]), exact, job_id, w))
    rows.sort(key=lambda r: -r[0])
    if not rows:
        return out
    best = rows[0][0]
    kept, counts = [], {}
    for score, cos, exact, job_id, w in rows:
        if len(kept) >= limit or score < best - MARGIN:
            break
        if cos < FLOOR and not exact:
            continue
        if counts.get(job_id, 0) >= per_job:
            continue
        counts[job_id] = counts.get(job_id, 0) + 1
        kept.append((score, exact, job_id, w))
    names: dict[str, dict] = {}
    for score, exact, job_id, w in kept:
        if job_id not in names:
            try:
                names[job_id] = store.read_transcript(job_id)
            except (OSError, ValueError):
                names[job_id] = {}
        d = names[job_id]
        seg = next((s for s in d.get("segments", []) if s["id"] == w["seg"]), None)
        spk = d.get("speakers", {}).get(str(seg["speaker"]), "") if seg else ""
        out["results"].append({"job_id": job_id, "filename": d.get("filename", ""), "seg": w["seg"],
                               "segs": w["segs"], "start": w["start"], "speaker": spk, "text": w["text"],
                               "score": round(score, 3), "exact": exact})
    return out


# ---------------- background worker ----------------
_state: dict = {"job": None}
_wake = threading.Event()
_thread = None


def busy() -> bool:
    """A transcription is running or waiting: the worker stays out of its way."""
    try:
        from . import pipeline

        return bool(pipeline._current.get("id") or pipeline.queue_ids())
    except Exception:
        return False


def kick() -> None:
    _wake.set()


def _lower_priority() -> None:
    if os.name == "nt":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            k.SetThreadPriority(k.GetCurrentThread(), -2)  # THREAD_PRIORITY_LOWEST
        except Exception:
            pass


def stale_jobs() -> list[str]:
    """Done recordings whose index is missing or older than the transcript (newest first)."""
    out = []
    for j in _job_ids():
        try:
            mt = _transcript_mtime(j)
        except OSError:
            continue
        if time.time() - mt / 1e9 < SETTLE_SECONDS or is_fresh(j) or _skipped.get(j) == mt:
            continue
        out.append((mt, j))
    return [j for _, j in sorted(out, reverse=True)]


_skipped: dict[str, int] = {}  # job id -> transcript mtime that was found not indexable (not done yet / empty)


def work_once(embedder=None) -> int:
    """One pass over the stale recordings; stops as soon as a transcription starts. Returns how many were indexed."""
    n = 0
    for j in stale_jobs():
        if busy():
            break
        _state["job"] = j
        try:
            r = index_job(j, embedder, should_stop=busy)
            if r == "skipped":
                _skipped[j] = _transcript_mtime(j)
            elif r != "fresh":
                n += 1
        except InterruptedError:
            break
        except Exception:
            import traceback

            traceback.print_exc()
        finally:
            _state["job"] = None
        time.sleep(0.05)  # let other threads in
    return n


def _loop() -> None:
    _lower_priority()
    while True:
        _wake.wait(POLL_SECONDS)
        _wake.clear()
        try:
            if is_downloaded() and not busy():
                work_once()
        except Exception:
            import traceback

            traceback.print_exc()


def start_worker() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, daemon=True, name="semantic-index")
        _thread.start()
    kick()


def status() -> dict:
    return {"model": MODEL["name"], "label": MODEL["label"], "size": MODEL["size"], "downloaded": is_downloaded(),
            "download": download_status(), "indexing": bool(_state.get("job")), **coverage()}
