# -*- mode: python -*-
# Build: .\build_windows.ps1   (CPU build; add -Gpu for the NVIDIA variant)
from PyInstaller.utils.hooks import collect_all

import os
datas = [("frontend", "frontend"), ("assets", "assets")]
# speaker models only (small). The speech model (whisper large-v3-turbo) is NOT in the package: it is downloaded on
# first start into %APPDATA%\SesDefteriBasit\models. A "whisper-large-v3-turbo" folder next to SesDefteri.exe is used
# instead of downloading (backend/models.py bundled()). No language models.
for n in os.listdir("models"):
    if n not in ("llm", "whisper-large-v3-turbo"):
        src = os.path.join("models", n)
        datas.append((src, src if os.path.isdir(src) else "models"))
binaries = []
hiddenimports = ["backend.bridge", "backend.window", "backend.names", "backend.people",
                 "backend.system_api", "backend.engines.ct2", "backend.engines.whispercpp",
                 "backend.analysis", "backend.minutes", "backend.meeting_recorder", "backend.updater", "backend.names_llm", "backend.llm", "backend.llm.catalog", "backend.llm_api"]
# packages with native DLLs or data files (VAD model, docx template, WebView2 bridge …)
for pkg in ("faster_whisper", "ctranslate2", "sherpa_onnx", "onnxruntime", "av", "webview",
            "clr_loader", "pythonnet", "tokenizers", "docx", "sounddevice", "_sounddevice_data", "soundcard", "cffi"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Visual C++ runtime: always inside the package so a PC without the "VC++ Redistributable" still works
# (ctranslate2, onnxruntime, sherpa-onnx, av and Python itself import these).
import sys as _sys
_vc_dirs = [_sys.base_prefix, os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]
for _n in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
           "concrt140.dll", "vcomp140.dll"):
    for _d in _vc_dirs:
        _p = os.path.join(_d, _n)
        if os.path.isfile(_p):
            binaries.append((_p, "."))
            break

# whisper.cpp Vulkan runtime (onboard Radeon / any Vulkan GPU). The self-test picks it only if it is faster here.
_wc = "vendor/whispercpp"
if os.path.isdir(_wc):
    for f in os.listdir(_wc):
        binaries.append((os.path.join(_wc, f), "whispercpp"))
    # whisper-cli.exe is a child process: it does not see the VC++ DLLs in the package root, so put them next to it
    for _n in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        for _d in _vc_dirs:
            _p = os.path.join(_d, _n)
            if os.path.isfile(_p):
                binaries.append((_p, "whispercpp"))
                break
hiddenimports.append("backend.engines.tuning")

a = Analysis(
    ["app.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports,
    excludes=["nvidia", "tkinter", "matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SesDefteri",
          console=False, icon="assets/icon.ico", version="installer/version_info.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="SesDefteri")
