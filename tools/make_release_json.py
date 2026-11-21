"""Write site/ses-defteri/surum.json: the version file the installed apps read at start (backend/updater.py).

    python tools/make_release_json.py --notes-tr notes_tr.txt --notes-en notes_en.txt \
        --standart dist/SesDefteri-Setup.exe --nvidia dist/SesDefteri-NVIDIA-Setup.exe \
        --basit "../../Basit Sürüm/SesDefteri-Basit-Setup.exe"

Size and SHA-256 come from the files themselves; the download links point to the GitHub release of this version, so
upload the same files there (tools/dev/upload.sh v<version> ...). Then upload the site/ses-defteri folder to
selimoguz.com.tr/ses-defteri/ with the hosting panel.
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.updater import DOWNLOAD_PREFIX, validate  # noqa: E402
from backend.version import VERSION  # noqa: E402


def entry(path: Path, version: str) -> dict:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return {"url": f"{DOWNLOAD_PREFIX}v{version}/{path.name}", "size": path.stat().st_size, "sha256": h.hexdigest()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--version", default=VERSION)
    p.add_argument("--notes-tr", type=Path)
    p.add_argument("--notes-en", type=Path)
    for ed in ("standart", "nvidia", "basit"):
        p.add_argument(f"--{ed}", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "site" / "ses-defteri" / "surum.json")
    a = p.parse_args()
    files = {ed: entry(getattr(a, ed), a.version) for ed in ("standart", "nvidia", "basit") if getattr(a, ed)}
    if not files:
        p.error("give at least one setup file")
    m = {"version": a.version, "date": datetime.date.today().isoformat(),
         "notes_tr": a.notes_tr.read_text("utf-8").strip() if a.notes_tr else "",
         "notes_en": a.notes_en.read_text("utf-8").strip() if a.notes_en else "",
         "files": files}
    validate(m)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{a.out}: {a.version}, {', '.join(files)}")


if __name__ == "__main__":
    main()
