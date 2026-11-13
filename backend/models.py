"""Whisper model choice, recommendation and download (with real progress)."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import store

GB = 1024 ** 3

# vram = measured/estimated GPU memory incl. the CUDA context at float16; size = download size.
MODELS = {
    "large-v3-turbo": {"repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "size": int(1.62 * GB),
                       "vram": 2.3, "ram": 3.0, "quality": 3, "speed": 2},
    "medium": {"repo": "Systran/faster-whisper-medium", "size": int(1.53 * GB),
               "vram": 3.0, "ram": 3.0, "quality": 2, "speed": 1},
    "small": {"repo": "Systran/faster-whisper-small", "size": int(0.48 * GB),
              "vram": 1.4, "ram": 1.5, "quality": 1, "speed": 3},
}
DEFAULT = os.environ.get("SESDEFTERI_MODEL") or os.environ.get("MEETTRANSCRIBER_MODEL", "large-v3-turbo")


def root() -> Path:
    """Where Whisper models live (SESDEFTERI_MODEL_DIR, or the older MEETTRANSCRIBER_MODEL_DIR, overrides, e.g. for tests)."""
    env = os.environ.get("SESDEFTERI_MODEL_DIR") or os.environ.get("MEETTRANSCRIBER_MODEL_DIR")
    return Path(env) if env else store.data_dir() / "models"


def bundled(name: str = "large-v3-turbo") -> Path | None:
    """Folder of a speech model that needs no download: one shipped with / next to the program, or the one the
    first-start download put in the data folder (models/ct2-<name>). None if neither is complete.
    SESDEFTERIBASIT_NO_BUNDLED=1 ignores the shipped copies (to try the first-start download from source)."""
    import sys

    if name != "large-v3-turbo":
        return None
    cands: list[Path] = []
    if not os.environ.get("SESDEFTERIBASIT_NO_BUNDLED"):
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).resolve().parent
            cands += [Path(getattr(sys, "_MEIPASS", "")) / "whisper", exe / "whisper-large-v3-turbo",
                      exe / "models" / "whisper-large-v3-turbo"]
        else:
            cands.append(Path(__file__).resolve().parents[1] / "models" / "whisper-large-v3-turbo")
    cands.append(ct2_dir(name))
    return next((c for c in cands if (c / "model.bin").is_file() and _ct2_complete(c, name)), None)


def _cache_dir(name: str) -> Path:
    return root() / ("models--" + MODELS[name]["repo"].replace("/", "--"))


def is_downloaded(name: str) -> bool:
    if name not in MODELS:
        return False
    if bundled(name):
        return True
    return any(p.is_file() for p in (_cache_dir(name) / "snapshots").glob("*/model.bin"))


def downloaded() -> list[str]:
    return [n for n in MODELS if is_downloaded(n)]


def disk_bytes(name: str) -> int:
    total = 0
    for p in _cache_dir(name).rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def effective_vram_gb(hw: dict, plan_device: str) -> float | None:
    """GPU memory that the engine may use, or None for CPU."""
    if plan_device == "cpu":
        return None
    from .hardware import best_gpu

    g = best_gpu(hw, "NVIDIA" if plan_device == "cuda" else None)
    if not g:
        return None
    return round((g.get("free") or g["vram"]) / GB, 1) if g["vram"] else None


def recommend(hw: dict, plan_device: str) -> str:
    """Best model for this PC. Rules are deliberately simple and explainable."""
    vram = effective_vram_gb(hw, plan_device)
    ram = hw.get("ram", {}).get("total_gb") or 0
    cores = hw.get("cpu", {}).get("cores") or 1
    if plan_device != "cpu":
        if vram is None or vram >= 3.0:  # unknown VRAM: assume a normal card
            return "large-v3-turbo"
        return "small"
    # CPU only: the big model is ~3x slower than 'small'
    if ram and ram < 6:
        return "small"
    return "large-v3-turbo" if cores >= 8 else "small"


def fit(name: str, hw: dict, plan_device: str, compute: str = "float16") -> str:
    """'ok' | 'tight' | 'cpu' - does the model comfortably fit the device that will run it?"""
    if plan_device == "cpu":
        return "cpu"
    vram = effective_vram_gb(hw, plan_device)
    if vram is None:
        return "ok"
    need = MODELS[name]["vram"] * (0.7 if compute == "int8_float16" else 1.0)
    return "ok" if vram >= need + 1.0 else "tight" if vram >= need else "too_big"


def catalog(hw: dict, plan_device: str, compute: str, current: str) -> list[dict]:
    rec = recommend(hw, plan_device)
    return [{"id": n, "size": m["size"], "quality": m["quality"], "speed": m["speed"],
             "downloaded": is_downloaded(n), "recommended": n == rec, "current": n == current,
             "fit": fit(n, hw, plan_device, compute)} for n, m in MODELS.items()]


# ---------------- download with progress ----------------
_dl: dict = {"state": "idle", "model": None, "done": 0, "total": 0, "error": None}
_dl_lock = threading.Lock()


def download_status() -> dict:
    with _dl_lock:
        return dict(_dl)


def start_download(name: str) -> dict:
    if name not in MODELS:
        raise ValueError("unknown model")
    with _dl_lock:
        if _dl["state"] == "running":
            return dict(_dl)
        _dl.update(state="running", model=name, done=disk_bytes(name), total=MODELS[name]["size"], error=None)
    threading.Thread(target=_download, args=(name,), daemon=True).start()
    return download_status()


def _download(name: str) -> None:
    stop = threading.Event()

    def poll():  # bytes on disk (incl. *.incomplete files) against the known size
        while not stop.wait(0.4):
            with _dl_lock:
                _dl["done"] = min(disk_bytes(name), MODELS[name]["size"])

    threading.Thread(target=poll, daemon=True).start()
    try:
        from faster_whisper.utils import download_model

        root().mkdir(parents=True, exist_ok=True)
        download_model(MODELS[name]["repo"], cache_dir=str(root()))
        stop.set()
        with _dl_lock:
            _dl.update(state="done", done=_dl["total"])
    except Exception as e:
        stop.set()
        with _dl_lock:
            _dl.update(state="error", error=f"{type(e).__name__}: {e}")


# ======================================================================================================
# First-start download (Ses Defteri Basit): no choice, no question. Everything below is plain urllib with
# HTTP Range, so a closed app or a cut connection continues from the *.incomplete file.
# ======================================================================================================
import errno
import shutil
import urllib.error
import urllib.request
from collections import deque

# CTranslate2 model (faster-whisper): (file, exact size in bytes). model.bin last: it is the big one.
CT2_FILES = {
    "large-v3-turbo": [("config.json", 2263), ("preprocessor_config.json", 340), ("tokenizer.json", 2710337),
                       ("vocabulary.json", 1068114), ("model.bin", 1617884929)],
}
CT2_URL = "https://huggingface.co/{repo}/resolve/main/{file}"
# whisper.cpp ggml models (Vulkan / Radeon). The q5_0 file is the small, fast one.
GGML = {
    "large-v3-turbo": {"size": 1624555275},
    "large-v3-turbo-q5_0": {"size": 574041195},
}
GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
# What the first start fetches ("ct2:<name>" or "ggml:<name>"). Edit here to change what is downloaded.
FIRST_RUN_ITEMS = ("ct2:large-v3-turbo", "ggml:large-v3-turbo-q5_0")
LABELS = {"ct2": "Ses tanıma modeli", "ggml": "Ekran kartı için hızlı model"}
RETRY_DELAYS = (3, 8, 20)  # seconds between the (up to) 4 tries in a row
_CHUNK = 256 * 1024
_urlopen = urllib.request.urlopen  # tests replace these three
_sleep = time.sleep
_now = time.monotonic


def ct2_dir(name: str = "large-v3-turbo") -> Path:
    return root() / f"ct2-{name}"


def _ct2_complete(folder: Path, name: str) -> bool:
    """Every file is there (a downloaded folder only has real names when complete)."""
    return all((folder / f).is_file() for f, _ in CT2_FILES.get(name, [("model.bin", 0)]))


def ggml_dir() -> Path:
    return root() / "ggml"  # the same folder the whisper.cpp engine reads (data_dir/models/ggml)


def ggml_path(name: str = "large-v3-turbo") -> Path | None:
    """Path of a downloaded ggml model (e.g. "large-v3-turbo" or "large-v3-turbo-q5_0"), None if it is not
    completely there. Partial downloads are *.incomplete files and never count."""
    info = GGML.get(name)
    p = ggml_dir() / f"ggml-{name}.bin"
    if info and p.is_file() and p.stat().st_size == info["size"]:
        return p
    return None


def _item(item_id: str) -> dict:
    kind, _, name = item_id.partition(":")
    if kind == "ct2":
        d = ct2_dir(name)
        files = [{"url": CT2_URL.format(repo=MODELS[name]["repo"], file=f), "dest": d / f, "size": n}
                 for f, n in CT2_FILES[name]]
    elif kind == "ggml":
        files = [{"url": GGML_URL.format(name=name), "dest": ggml_dir() / f"ggml-{name}.bin", "size": GGML[name]["size"]}]
    else:
        raise ValueError("unknown item")
    return {"id": item_id, "label": LABELS[kind], "files": files}


def _file_done(f: dict) -> bool:
    d = f["dest"]
    return d.is_file() and d.stat().st_size == f["size"]


def _have(f: dict) -> int:
    if _file_done(f):
        return f["size"]
    part = f["dest"].with_name(f["dest"].name + ".incomplete")
    try:
        return min(part.stat().st_size, f["size"])
    except OSError:
        return 0


_fr_lock = threading.Lock()
_fr: dict = {"state": "idle", "error": None, "kind": None, "retrying": False, "attempt": 0,
             "live": {}, "samples": deque(), "thread": None}

T_NO_INTERNET = ("İnternete bağlanılamadı. Bağlantını kontrol et (Wi-Fi ya da kablo), sonra \"Tekrar dene\"ye bas. "
                 "İndirilen kısım silinmez, kaldığı yerden devam eder.")
T_ERROR = ("İndirme sırasında bir sorun oldu. \"Tekrar dene\"ye bas. Yine olmazsa biraz sonra tekrar dene; "
           "indirilen kısım silinmez.")
T_DISK = "Bilgisayarında yeterli boş yer yok. Yaklaşık {gb} GB boş yer aç, sonra \"Tekrar dene\"ye bas."


class _Incomplete(Exception):
    pass


def _fetch(url: str, dest: Path, expected: int, on_bytes) -> None:
    """Download one file to dest. Resumes from dest.incomplete; the file only gets its real name when complete."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".incomplete")
    have = part.stat().st_size if part.exists() else 0
    if have > expected:
        part.unlink()
        have = 0
    headers = {"User-Agent": "SesDefteri"}
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        r = _urlopen(urllib.request.Request(url, headers=headers), timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # asked for bytes beyond the end: it was already complete
            if have == expected:
                os.replace(part, dest)
                return
            part.unlink()
            raise _Incomplete("range") from e
        raise
    with r:
        status = getattr(r, "status", 200)
        if have and status != 206:  # the server sent everything again: start from zero
            have = 0
        length = int(r.headers.get("Content-Length") or 0)
        total = have + length if length else expected
        with open(part, "ab" if have else "wb") as out:
            done = have
            on_bytes(done)
            while True:
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                on_bytes(done)
    if done != total or done != expected:
        raise _Incomplete(f"{done}/{total}")
    os.replace(part, dest)


def _classify(e: BaseException) -> str:
    """'disk' | 'error' (the server said no) | 'no_internet' (anything else on the wire)."""
    if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ENOSPC:
        return "disk"
    if isinstance(e, urllib.error.HTTPError):
        return "error"
    return "no_internet"


def _record(path: Path, done: int) -> None:
    with _fr_lock:
        _fr["live"][str(path)] = done
        s = _fr["samples"]
        t = _now()
        s.append((t, sum(_fr["live"].values())))
        while len(s) > 2 and t - s[0][0] > 8:
            s.popleft()


def _fail(kind: str, text: str) -> None:
    with _fr_lock:
        _fr.update(state="no_internet" if kind == "no_internet" else "error", error=text, kind=kind, retrying=False)


def _run_first_run(item_ids: tuple) -> None:
    try:
        items = [_item(i) for i in item_ids]
        files = [f for it in items for f in it["files"] if not _file_done(f)]
        root().mkdir(parents=True, exist_ok=True)
        need = sum(f["size"] - _have(f) for f in files)
        free = shutil.disk_usage(root()).free
        if need and free < need + 300 * 1024 * 1024:
            gb = (need + 300 * 1024 * 1024 - free) / GB
            return _fail("disk", T_DISK.format(gb=f"{gb:.1f}".replace(".", ",")))
        for f in files:
            fails = 0
            while True:
                start_have = _have(f)
                with _fr_lock:
                    _fr["retrying"] = False
                try:
                    _fetch(f["url"], f["dest"], f["size"], lambda d, f=f: _record(f["dest"], d))
                    break
                except Exception as e:
                    if _have(f) > start_have:
                        fails = 0  # it moved forward before it broke: not a dead end
                    kind = _classify(e)
                    if kind == "disk":
                        return _fail(kind, T_DISK.format(gb="1"))
                    if fails >= len(RETRY_DELAYS) or (kind == "error" and fails >= 1):
                        return _fail(kind, T_NO_INTERNET if kind == "no_internet" else T_ERROR)
                    with _fr_lock:
                        _fr["retrying"] = True
                        _fr["attempt"] = fails + 1
                    _sleep(RETRY_DELAYS[fails])
                    fails += 1
        with _fr_lock:
            _fr.update(state="done", error=None, kind=None, retrying=False)
    except Exception as e:  # never leave the screen waiting
        _fail("error", T_ERROR + f" ({type(e).__name__})")


def first_run_status(item_ids: tuple | None = None) -> dict:
    """What the first-start screen shows. state: idle (something is missing, not started), downloading,
    done (nothing missing), error, no_internet. Bytes are per file and in total; speed in bytes/s (about the last
    8 seconds); eta in seconds or None while unknown."""
    ids = item_ids or FIRST_RUN_ITEMS
    items = [_item(i) for i in ids]
    with _fr_lock:
        live = dict(_fr["live"])
        state, error, kind, retrying, attempt = _fr["state"], _fr["error"], _fr["kind"], _fr["retrying"], _fr["attempt"]
        samples = list(_fr["samples"])
    out_items, done_t, total_t = [], 0, 0
    for it in items:
        d = sum(f["size"] if _file_done(f) else min(f["size"], max(live.get(str(f["dest"]), 0), _have(f))) for f in it["files"])
        t = sum(f["size"] for f in it["files"])
        out_items.append({"id": it["id"], "label": it["label"], "done": d, "total": t, "complete": d >= t})
        done_t += d
        total_t += t
    needed = done_t < total_t
    if not needed:
        state = "done"
    elif state == "done":  # the files vanished after a finished run
        state = "idle"
    speed = 0.0
    if state == "downloading" and len(samples) >= 2 and samples[-1][0] > samples[0][0]:
        speed = max(0.0, (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]))
        if _now() - samples[-1][0] > 4:  # nothing arrived for a while
            speed = 0.0
    eta = round((total_t - done_t) / speed) if speed > 1 and needed else None
    failed = state in ("error", "no_internet")
    return {"needed": needed, "state": state, "done": done_t, "total": total_t, "items": out_items,
            "speed": round(speed), "eta": eta, "retrying": bool(retrying and state == "downloading"), "attempt": attempt,
            "error": error if failed else None, "kind": kind if failed else None}


def first_run_needed(item_ids: tuple | None = None) -> bool:
    return first_run_status(item_ids)["needed"]


def first_run_blocking() -> bool:
    """True while a start-up download is running or stopped half way (new recordings must wait)."""
    st = first_run_status()
    return st["needed"] and st["state"] in ("downloading", "error", "no_internet")


def start_first_run_download(item_ids: tuple | None = None) -> dict:
    """Start (or restart after an error) the download of everything that is missing. Safe to call twice."""
    ids = tuple(item_ids or FIRST_RUN_ITEMS)
    with _fr_lock:
        th = _fr["thread"]
        running = th is not None and th.is_alive()
    if not running and first_run_status(ids)["needed"]:
        with _fr_lock:
            _fr.update(state="downloading", error=None, kind=None, retrying=False, attempt=0, live={}, samples=deque())
            _fr["thread"] = threading.Thread(target=_run_first_run, args=(ids,), daemon=True)
            _fr["thread"].start()
    return first_run_status(ids)


def ensure(item_ids: tuple | None = None, wait: bool = False) -> dict:
    """models.ensure(("ct2:large-v3-turbo", "ggml:large-v3-turbo-q5_0")): download what is missing (background
    thread). wait=True blocks until it ends. Returns first_run_status()."""
    st = start_first_run_download(item_ids)
    if wait:
        th = _fr["thread"]
        if th is not None:
            th.join()
        st = first_run_status(item_ids)
    return st
