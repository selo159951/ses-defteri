"""The one place the app version lives. build_windows.ps1 reads it for the exe's version resource and the installer."""
from __future__ import annotations

import os
import sys
from pathlib import Path

VERSION = "1.4.0"
# Code-signing certificate ("CN=Selim Oğuz", made by tools/make_cert.ps1): the updater only installs setups signed by it.
SIGNER_THUMBPRINT = "8032931C62F4F826CF46A2566FCCBBE05130D6F3"
EDITIONS = ("standart", "nvidia", "basit")


def edition() -> str:
    """Which package is running: 'standart', 'nvidia' or 'basit' (written by the build), 'dev' from source."""
    override = os.environ.get("SESDEFTERI_EDITION", "").strip().lower()
    if override:
        return override
    base = getattr(sys, "_MEIPASS", None)
    if base:
        try:
            name = (Path(base) / "edition.txt").read_text(encoding="utf-8").strip().lower()
            if name in EDITIONS:
                return name
        except OSError:
            pass
        return "nvidia" if (Path(base) / "nvidia").is_dir() else "standart"
    return "dev"


def parse(v: str) -> tuple[int, ...]:
    """'1.10.0' -> (1, 10, 0); a leading 'v' and suffixes like '-beta' are ignored; junk -> (0,)."""
    v = str(v or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    try:
        parts = tuple(int(p) for p in v.split("."))
    except ValueError:
        return (0,)
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts or (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return parse(candidate) > parse(current)
