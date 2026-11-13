"""Compatibility logic: WebView2 detection, compute-type fallback, zip/temp detection, RAM, errors."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import compat  # noqa: E402

GB = 1024 ** 3
WV2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def reg(values: dict):
    return lambda hive, sub, name: values.get((hive, sub, name))


NET = ("HKLM", r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release")


def test_webview2_ok_machine_wide():
    r = reg({NET: 528040, ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WV2}", "pv"): "120.0.2210.91"})
    assert compat.webview2_status(r) == "ok"


def test_webview2_ok_per_user():
    r = reg({NET: 528040, ("HKCU", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WV2}", "pv"): "109.0.1518.78"})
    assert compat.webview2_status(r) == "ok"


def test_webview2_missing_or_zero_or_too_old():
    assert compat.webview2_status(reg({NET: 528040})) == "webview2"
    k = ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WV2}", "pv")
    assert compat.webview2_status(reg({NET: 528040, k: "0.0.0.0"})) == "webview2"
    assert compat.webview2_status(reg({NET: 528040, k: "85.0.564.0"})) == "webview2"


def test_dotnet_too_old():
    k = ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WV2}", "pv")
    assert compat.webview2_status(reg({k: "120.0.1.1"})) == "dotnet"
    assert compat.webview2_status(reg({NET: 393295, k: "120.0.1.1"})) == "dotnet"


def test_messages_are_turkish_and_have_link():
    assert "LinkId=2124703" in compat.MSG_WEBVIEW2 and "Ses Defteri" in compat.MSG_WEBVIEW2


@pytest.mark.parametrize("sup,expect", [
    ({"int8", "int8_float32", "float32"}, ["int8", "int8_float32", "float32"]),
    ({"float32"}, ["float32"]),
    ({"int8_float32", "float32", "int16"}, ["int8_float32", "float32"]),
    (None, ["int8", "int8_float32", "float32"]),
    (set(), ["int8", "int8_float32", "float32"]),
    ({"int16"}, ["int8", "int8_float32", "float32"]),
])
def test_compute_chain(sup, expect):
    assert compat.compute_chain(sup) == expect


def test_cpu_threads():
    assert compat.cpu_threads(2) == 2 and compat.cpu_threads(1) == 1
    assert compat.cpu_threads(32) == 8 and compat.cpu_threads(None) == 2 and compat.cpu_threads(0) == 2


def test_check_os():
    assert compat.check_os((6, 1, 7601))  # Windows 7
    assert compat.check_os((10, 0, 19045), is_64bit=False)
    assert compat.check_os((10, 0, 19045)) is None
    assert compat.check_os(None) is None


@pytest.mark.parametrize("path,tmp,expect", [
    (r"C:\Users\Ali\AppData\Local\Temp\Temp1_SesDefteri-Basit.zip\SesDefteri-Basit", None, True),
    (r"C:\Users\Ali\Downloads\SesDefteri-Basit.zip\SesDefteri-Basit", None, True),
    (r"C:\Users\Ali\AppData\Local\Temp\7zO12345\SesDefteri", None, True),
    (r"C:\Users\Ali\AppData\Local\Temp\Rar$EXa0.123\SesDefteri", None, True),
    (r"C:\Users\Ali\AppData\Local\Temp\xyz", r"C:\Users\Ali\AppData\Local\Temp", True),
    (r"c:\users\ali\appdata\local\temp", r"C:\Users\Ali\AppData\Local\Temp", True),
    (r"C:\Users\Şükrü\Desktop\SesDefteri-Basit", r"C:\Users\Şükrü\AppData\Local\Temp", False),
    (r"C:\Users\Ali\OneDrive\Masaüstü\SesDefteri Basit", r"C:\Users\Ali\AppData\Local\Temp", False),
    (r"D:\Programlar\SesDefteri-Basit", None, False),
])
def test_running_from_zip(path, tmp, expect):
    assert compat.running_from_zip(path, tmp) is expect


def test_ram_warning():
    assert compat.ram_warning(None) is None
    assert compat.ram_warning(16 * GB) is None
    assert compat.ram_warning(int(7.9 * GB)) is None
    w = compat.ram_warning(int(3.8 * GB))
    assert w and "3.8" in w and "RAM" in w


def test_memory_error_detection_and_friendly():
    assert compat.is_memory_error(MemoryError())
    assert compat.is_memory_error(RuntimeError("std::bad_alloc"))
    assert compat.is_memory_error(OSError("The paging file is too small for this operation to complete"))
    assert not compat.is_memory_error(ValueError("bad file"))
    assert "belleği yetmedi" in compat.friendly_error(MemoryError())
    assert "Visual C++" in compat.friendly_error(ImportError("DLL load failed while importing _ext"))
    assert "Beklenmeyen" in compat.friendly_error(KeyError("x"))


def test_create_cpu_falls_back_through_compute_types(monkeypatch):
    from backend.engines import ct2

    tried = []

    def fake_create(self, model, device, compute):
        tried.append(compute)
        if compute != "float32":
            raise ValueError(f"Requested int8 compute type, but the target device does not support it ({compute})")
        return "MODEL"

    monkeypatch.setattr(ct2.CT2Engine, "_create", fake_create)
    e = ct2.CT2Engine("cpu", "int8")
    assert e._create_cpu("large-v3-turbo") == "MODEL"
    assert tried[0] == "int8" and tried[-1] == "float32" and e.compute == "float32"


def test_create_cpu_memory_error_is_readable_and_stops(monkeypatch):
    from backend.engines import ct2

    tried = []

    def fake_create(self, model, device, compute):
        tried.append(compute)
        raise MemoryError()

    monkeypatch.setattr(ct2.CT2Engine, "_create", fake_create)
    with pytest.raises(RuntimeError, match="belleği yetmedi"):
        ct2.CT2Engine("cpu", "int8")._create_cpu("large-v3-turbo")
    assert len(tried) == 1  # a bigger compute type would need even more memory


def test_transcribe_memory_error_becomes_readable(monkeypatch):
    from backend.engines import ct2

    e = ct2.CT2Engine("cpu", "int8")
    monkeypatch.setattr(e, "_transcribe", lambda *a: (_ for _ in ()).throw(RuntimeError("std::bad_alloc")))
    with pytest.raises(RuntimeError, match="belleği yetmedi"):
        e.transcribe(None, 1.0, lambda p: None)


def test_non_ascii_paths_decode(tmp_path):
    """PyAV reads and writes under a folder with Turkish letters and spaces."""
    import wave

    import numpy as np

    from backend import audio

    d = tmp_path / "Şükrü Ödev Ğ ıİ"
    d.mkdir()
    wav = d / "toplantı kaydı.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes((np.sin(np.arange(16000) / 5) * 8000).astype("<i2").tobytes())
    samples, dur = audio.convert(wav, d / "çıktı.mp3")
    assert abs(dur - 1.0) < 0.1 and (d / "çıktı.mp3").stat().st_size > 0
