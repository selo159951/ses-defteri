"""Write installer/version_info.txt from backend/version.py and print the version (build_windows.ps1 passes it to Inno).

    python tools/set_version.py   ->  1.3.0
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.version import VERSION  # noqa: E402


def main() -> None:
    nums = [int(n) for n in VERSION.split(".")] + [0, 0, 0, 0]
    four = ", ".join(str(n) for n in nums[:4])
    path = ROOT / "installer" / "version_info.txt"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"filevers=\([^)]*\)", f"filevers=({four})", text)
    text = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({four})", text)
    text = re.sub(r"StringStruct\('(File|Product)Version', '[^']*'\)", lambda m: f"StringStruct('{m[1]}Version', '{VERSION}')", text)
    path.write_text(text, encoding="utf-8")
    print(VERSION)


if __name__ == "__main__":
    main()
