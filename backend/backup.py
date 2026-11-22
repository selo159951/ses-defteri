"""Backup and restore: the whole data folder in one .zip.

Models, the webview cache, the llm folder, recordings still being written and
half-written files (*.part, *.log) are left out: they are bulky or rebuilt by
the app itself. The zip work runs in a thread; the page polls status()."""
from __future__ import annotations

import json
import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from . import store, version

APP_NAME = "Ses Defteri"
MANIFEST = "manifest.json"
SKIP_DIRS = {"models", "webview", "llm"}        # several GB, or private to the running window
SKIP_SUFFIXES = (".part", ".log")                # half-written files
IN_PROGRESS = ("recording", "stopped")           # a recording folder's meta.json state

_lock = threading.Lock()
_status = {"busy": False, "kind": "", "path": "", "error": "", "done": False, "files": 0, "result": None}


def status() -> dict:
    with _lock:
        return dict(_status)


def _set(**fields) -> None:
    with _lock:
        _status.update(fields)


def run_in_thread(kind: str, fn, path: str = "") -> None:
    """Run fn() in the background; the page follows along with status(). Raises while another one runs."""
    if status()["busy"]:
        raise ValueError("a backup is already being made")
    _set(busy=True, kind=kind, path=path, error="", done=False, files=0, result=None)

    def work():
        try:
            result = fn()
            _set(busy=False, done=True, result=result)
        except Exception as e:
            _set(busy=False, error=str(e)[:300])

    threading.Thread(target=work, daemon=True).start()


def default_name(prefix: str = "yedek") -> str:
    """Ready-made file name for a backup: SesDefteri-yedek-2026-11-23.zip"""
    return f"SesDefteri-{prefix}-{datetime.now():%Y-%m-%d}.zip"


def _recording_in_progress(folder: Path) -> bool:
    try:
        meta = json.loads((folder / "meta.json").read_text("utf-8"))
        return meta.get("state") in IN_PROGRESS
    except (OSError, ValueError):
        return False


def _files(root: Path) -> list[Path]:
    """The files that belong in a backup, as names relative to the data folder."""
    in_progress: set[str] = set()
    rec = root / "recordings"
    if rec.is_dir():
        for d in rec.iterdir():
            if d.is_dir() and _recording_in_progress(d):
                in_progress.add(d.name)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts[0] in SKIP_DIRS:
            continue
        if rel.parts[0] == "recordings" and len(rel.parts) > 1 and rel.parts[1] in in_progress:
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        out.append(rel)
    return out


def create(target: Path) -> dict:
    """Zip the data folder into target. Returns {path, files, bytes}."""
    root = store.data_dir()
    target = Path(target)
    if target.suffix.lower() != ".zip":
        target = target.with_name(target.name + ".zip")
    files = _files(root)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(
            {"app": APP_NAME, "version": version.VERSION, "created": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False, indent=1))
        for rel in files:
            z.write(root / rel, rel.as_posix())
    return {"path": str(target), "files": len(files), "bytes": target.stat().st_size}


def read_manifest(zip_path: Path) -> dict:
    """The manifest of a backup file; raises ValueError when it is not one of ours."""
    try:
        with zipfile.ZipFile(Path(zip_path)) as z:
            data = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise ValueError("this is not a Ses Defteri backup file") from e
    if not isinstance(data, dict) or data.get("app") != APP_NAME:
        raise ValueError("this is not a Ses Defteri backup file")
    return data


def _safe_dest(root: Path, name: str) -> Path | None:
    """Where a zip entry goes inside root, or None when it tries to escape the folder (zip-slip)."""
    root = root.resolve()
    dest = (root / name).resolve()
    return dest if root == dest or root in dest.parents else None


def restore(zip_path: Path, keep: Path | None = None) -> dict:
    """Extract a backup over the data folder (existing files are overwritten).
    The current data is saved first as SesDefteri-onceki-<date>.zip next to the chosen backup."""
    src = Path(zip_path)
    manifest = read_manifest(src)
    root = store.data_dir()
    if keep is None:
        keep = src.parent / f"SesDefteri-onceki-{datetime.now():%Y-%m-%d_%H%M}.zip"
    saved = create(keep)
    n = 0
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename == MANIFEST:
                continue
            dest = _safe_dest(root, info.filename)
            if dest is None:
                raise ValueError(f'"{info.filename}" does not belong inside the data folder')
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as fsrc, open(dest, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            n += 1
    return {"restored": n, "saved": saved["path"], "manifest": manifest}
