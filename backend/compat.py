"""Does this Windows PC meet what the app needs? Plain-Turkish messages instead of crashes.

Everything that decides something is a small pure function (registry reader, versions,
paths and memory sizes are passed in), so it is unit-tested without a real PC.
Windows calls (registry, MessageBox, GlobalMemoryStatusEx) are thin wrappers.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

GB = 1024 ** 3
TITLE = "Ses Defteri"
WEBVIEW2_LINK = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
DOTNET_LINK = "https://dotnet.microsoft.com/download/dotnet-framework/net48"

_WV2_GUIDS = ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",  # Evergreen runtime
              "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",  # beta
              "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",  # dev
              "{65C35B14-6C1D-4122-AC46-7148CC9D6497}")  # canary
NET462_RELEASE = 394802  # .NET Framework 4.6.2 (what pywebview/pythonnet need)

MSG_WEBVIEW2 = (
    "Bu bilgisayarda \"Microsoft Edge WebView2 Çalışma Zamanı\" yok. Program penceresini göstermek için bu gerekli.\n\n"
    "Ne yapmalı:\n"
    "1. İnternete bağlı bir bilgisayarda şu adresi açın:\n   " + WEBVIEW2_LINK + "\n"
    "2. \"Evergreen Standalone Installer\" (ya da \"Evergreen Bootstrapper\") dosyasını indirip çalıştırın.\n"
    "3. Kurulum bitince Ses Defteri'ni yeniden açın.\n\n"
    "(Windows 11'de ve güncel Windows 10'da bu zaten kuruludur.)")
MSG_DOTNET = (
    "Bu bilgisayarda \".NET Framework 4.6.2\" ya da daha yenisi yok. Program penceresi için gerekli.\n\n"
    "Windows Update ile Windows'u güncelleyin ya da şu adresten kurun:\n   " + DOTNET_LINK +
    "\nSonra Ses Defteri'ni yeniden açın.")
MSG_OLD_WINDOWS = (
    "Bu program Windows 10 ya da Windows 11 ister (64 bit). Bu bilgisayarın Windows'u çok eski.\n"
    "Programı daha yeni bir Windows'lu bilgisayarda açın.")
MSG_ZIP = (
    "Program zip dosyasının içinden ya da geçici bir klasörden açılmış gibi görünüyor.\n\n"
    "Önce zip dosyasına sağ tıklayıp \"Tümünü ayıkla\" deyin, sonra açılan klasörün içindeki "
    "SesDefteri.exe'yi çalıştırın.")
MSG_FILES_MISSING = (
    "Programın bazı dosyaları eksik (konuşma modeli bulunamadı).\n\n"
    "Zip dosyası tam çıkarılmamış ya da program klasörü bozulmuş olabilir. Zip'i yeniden "
    "\"Tümünü ayıkla\" ile bir klasöre çıkarın ve SesDefteri.exe'yi oradan açın. "
    "Antivirüs programı bazı dosyaları silmiş olabilir.")
MSG_DATA_DIR = (
    "Kayıtların saklanacağı klasör yazılamıyor:\n{path}\n\n"
    "Diskin dolu olmadığından ve klasörün korumalı olmadığından emin olun, sonra yeniden açın.")
MSG_LOW_RAM = (
    "Bu bilgisayarın belleği (RAM) az ({gb:.1f} GB). Program yine de çalışır ama yavaş olabilir.\n\n"
    "Başka programları (tarayıcı, Teams, Zoom vb.) kapatın ve uzun kayıtları tek tek işleyin. "
    "Bellek biterse iş \"hata\" olarak görünür; programı kapatıp yeniden açıp tekrar deneyin.\n"
    "(Bu uyarı bir kez gösterilir.)")
MSG_OLD_CPU = (
    "Bu bilgisayarın işlemcisi çok eski (AVX desteği yok). Program yavaş çalışabilir ya da hiç çalışmayabilir.\n"
    "Daha yeni bir bilgisayarda denemeniz önerilir.\n(Bu uyarı bir kez gösterilir.)")
MSG_GENERIC_START = (
    "Ses Defteri açılırken beklenmeyen bir sorun oldu ve açılamadı.\n\n"
    "Teknik ayrıntı:\n{err}\n\nAyrıntılı kayıt dosyası:\n{log}\n\n"
    "Bilgisayarı yeniden başlatıp tekrar deneyin. Olmazsa bu kayıt dosyasını programı veren kişiye gönderin.")


# ---------------- pure decisions ----------------
def _ver_tuple(s: str) -> tuple[int, ...]:
    out = []
    for p in str(s).split("."):
        if not p.isdigit():
            break
        out.append(int(p))
    return tuple(out)


def webview2_status(read) -> str:
    """'ok' | 'dotnet' | 'webview2'. read(hive, subkey, name) -> value or None (hive 'HKCU' | 'HKLM')."""
    rel = read("HKLM", r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release")
    try:
        if int(rel or 0) < NET462_RELEASE:
            return "dotnet"
    except (TypeError, ValueError):
        return "dotnet"
    for guid in _WV2_GUIDS:
        for hive, sub in (("HKCU", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
                          ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                          ("HKLM", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}")):
            pv = read(hive, sub, "pv")
            if pv and _ver_tuple(str(pv)) >= (86, 0, 622, 0):
                return "ok"
    return "webview2"


def check_os(version: tuple[int, int, int] | None, is_64bit: bool = True) -> str | None:
    """Message when Windows is too old / 32 bit, else None. version = (major, minor, build)."""
    if version is None:
        return None
    if version[0] < 10 or not is_64bit:
        return MSG_OLD_WINDOWS
    return None


def running_from_zip(exe_dir: str, temp_dir: str | None = None) -> bool:
    """True when the program folder is a temporary one (zip opened in Explorer, 7-Zip/WinRAR preview)."""
    p = os.path.normcase(os.path.normpath(str(exe_dir))).replace("/", "\\")
    for part in (x for x in p.split("\\") if x):
        if part.startswith(("temp1_", "7zo", "rar$ex")) or part.endswith(".zip"):
            return True
    if temp_dir:
        t = os.path.normcase(os.path.normpath(str(temp_dir))).replace("/", "\\")
        if p == t or p.startswith(t + "\\"):
            return True
    return False


def ram_warning(total_bytes: int | None) -> str | None:
    """Turkish warning when physical memory is below what the large speech model comfortably needs.
    (large-v3-turbo int8: ~1.5 GB model + ~0.5 GB speaker model + audio + the window ~ 3 GB peak.)"""
    if not total_bytes or total_bytes <= 0:
        return None
    if total_bytes < 5.5 * GB:  # a "4 GB" PC reports 3.5-4 GB usable, "6 GB" ~5.9
        return MSG_LOW_RAM.format(gb=total_bytes / GB)
    return None


COMPUTE_ORDER = ("int8", "int8_float32", "float32")


def compute_chain(supported) -> list[str]:
    """Compute types to try on CPU, smallest memory first. `supported` comes from
    ctranslate2.get_supported_compute_types("cpu"); unknown/empty -> try them all."""
    sup = set(supported or ())
    chain = [c for c in COMPUTE_ORDER if not sup or c in sup]
    return chain or list(COMPUTE_ORDER)


def cpu_threads(logical: int | None) -> int:
    return max(1, min(logical or 2, 8))


def is_memory_error(e: BaseException) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return isinstance(e, MemoryError) or any(k in s for k in (
        "bad_alloc", "not enough memory", "out of memory", "paging file", "cannot allocate", "yetersiz bellek"))


def friendly_error(e: BaseException, what: str = "konuşma modeli") -> str:
    """Turkish sentence for the job list; the technical text goes after it."""
    tech = f"{type(e).__name__}: {e}".strip().rstrip(":")
    if is_memory_error(e):
        return ("Bilgisayarın belleği yetmedi. Başka programları kapatıp programı yeniden açın ve tekrar deneyin "
                f"(çok uzun kayıtlar için kaydı parçalara bölmek de yardımcı olur). [{tech}]")
    if "dll" in tech.lower():
        return ("Programın gerekli bir parçası yüklenemedi. Windows'u güncelleyip bilgisayarı yeniden başlatın; "
                "olmazsa \"Microsoft Visual C++ Redistributable (x64)\" kurun: https://aka.ms/vs/17/release/vc_redist.x64.exe "
                f"[{tech}]")
    return f"Beklenmeyen bir sorun oldu ({what}). Programı kapatıp yeniden açın. [{tech}]"


# ---------------- Windows wrappers ----------------
def _reg_read(hive: str, sub: str, name: str):
    try:
        import winreg

        root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
        with winreg.OpenKey(root, sub) as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def windows_version() -> tuple[int, int, int] | None:
    try:
        v = sys.getwindowsversion()
        return (v.major, v.minor, v.build)
    except Exception:
        return None


def total_ram() -> int | None:
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile",
                                                  "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                                                  "ullAvailExtendedVirtual")]

        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return int(ms.ullTotalPhys) or None
    except Exception:
        return None


def cpu_has_avx() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(39))  # PF_AVX_INSTRUCTIONS_AVAILABLE
    except Exception:
        return True  # unknown: do not warn


def message_box(text: str, icon: int = 0x10, title: str = TITLE) -> None:
    """Native Windows message box (0x10 error, 0x30 warning, 0x40 info). Never raises."""
    try:
        print(f"[{title}] {text}", file=sys.stderr)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, icon | 0x10000)  # MB_SETFOREGROUND
        except Exception:
            pass


# ---------------- logging ----------------
def log_dir() -> Path:
    try:
        from . import store

        d = store.data_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path(tempfile.gettempdir()) / "SesDefteriBasit-logs"
        d.mkdir(parents=True, exist_ok=True)
        return d


def install_crash_logging() -> Path:
    """Log file with every uncaught error (main thread, other threads) and native crashes (faulthandler)."""
    import faulthandler
    import threading
    import traceback

    path = log_dir() / f"ses-defteri-{time.strftime('%Y%m%d')}.log"
    f = open(path, "a", encoding="utf-8", buffering=1)
    f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start, Windows {windows_version()}, "
            f"Python {sys.version.split()[0]}, exe {sys.executable}\n")
    if sys.stderr is None:
        sys.stderr = f
    if sys.stdout is None:
        sys.stdout = f
    try:
        faulthandler.enable(f, all_threads=True)
    except Exception:
        pass

    def hook(et, ev, tb):
        f.write("".join(traceback.format_exception(et, ev, tb)))

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    install_crash_logging.file = f  # keep it open for faulthandler
    return path


def mark_once(name: str) -> bool:
    """True the first time `name` is asked for (a flag file in the log folder), False afterwards."""
    try:
        flag = log_dir() / f"{name}.flag"
        if flag.exists():
            return False
        flag.write_text("1", "utf-8")
        return True
    except Exception:
        return False


def data_dir_writable() -> tuple[bool, str]:
    try:
        from . import store

        d = store.data_dir()
        t = d / ".write-test"
        t.write_text("x", "utf-8")
        t.unlink()
        return True, str(d)
    except Exception as e:
        return False, str(e)


# ---------------- startup ----------------
def startup_problem(exe_dir: str | None = None, frozen: bool | None = None) -> str | None:
    """First blocking problem as Turkish text, else None. Shows nothing itself."""
    if sys.platform != "win32":
        return None
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    m = check_os(windows_version(), is_64bit=sys.maxsize > 2 ** 32)
    if m:
        return m
    if frozen:
        d = exe_dir or str(Path(sys.executable).resolve().parent)
        if running_from_zip(d, tempfile.gettempdir()):
            return MSG_ZIP
        # the speech model is downloaded on first start now (no "model missing" check here)
    ok, detail = data_dir_writable()
    if not ok:
        return MSG_DATA_DIR.format(path=detail)
    st = webview2_status(_reg_read)
    if st == "dotnet":
        return MSG_DOTNET
    if st == "webview2":
        return MSG_WEBVIEW2
    return None


def startup_warnings() -> None:
    """Non-blocking notices, each shown once."""
    if sys.platform != "win32":
        return
    w = ram_warning(total_ram())
    if w and mark_once("ram-warned"):
        message_box(w, 0x30)
    if not cpu_has_avx() and mark_once("cpu-warned"):
        message_box(MSG_OLD_CPU, 0x30)
