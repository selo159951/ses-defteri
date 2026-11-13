"""CPU thread choice, the first-use engine self-test (fake engines, no model is ever loaded) and the fallbacks."""
import struct
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import asr, hardware, models  # noqa: E402
from backend.engines import tuning, whispercpp  # noqa: E402
from backend.engines.tuning import CPU, VULKAN  # noqa: E402
from backend.merge import Word  # noqa: E402

GB = 1024 ** 3
SPEECH = " Arkadaşlar herkese merhaba bugünkü toplantıya başlıyoruz önce geçen haftanın işlerine bakalım"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path))
    monkeypatch.setenv("SESDEFTERIBASIT_MODEL_DIR", str(tmp_path / "models"))
    asr.release()
    yield
    asr.release()


def hw(*, gpus=True, vulkan=True, physical=6, logical=12):
    g = [{"name": "AMD Radeon(TM) Graphics", "vendor": "AMD", "vram": 2 * GB, "vram_gb": 2.0, "integrated": True}]
    return {"gpus": g if gpus else [], "vulkan": vulkan,
            "cpu": {"name": "AMD Ryzen 5 5625U", "cores": logical, "physical": physical},
            "ram": {"total_gb": 16, "total": 16 * GB, "available": 8 * GB}}


# ---------------- threads ----------------
def core_record(relationship, ptr=8):
    pad = b"\0" * 4 if ptr == 8 else b""
    return struct.pack("<Q" if ptr == 8 else "<I", 0x3) + struct.pack("<I", relationship) + pad + b"\0" * 16


@pytest.mark.parametrize("ptr", (4, 8))
def test_core_count_from_windows_buffer(ptr):
    # Ryzen 5 5625U: 6 cores (+ caches, a NUMA node and a package record that must not be counted)
    buf = b"".join(core_record(r, ptr) for r in [0] * 6 + [1, 2, 2, 2, 3])
    assert hardware._count_cores_in_buffer(buf, ptr) == 6
    assert hardware._count_cores_in_buffer(b"", ptr) == 0


def test_cpu_threads_is_physical_core_count():
    assert hardware.cpu_threads(6) == 6          # the target PC: 6 cores / 12 threads -> 6, not 12
    assert hardware.cpu_threads(2) == 2 and hardware.cpu_threads(1) == 1
    assert hardware.cpu_threads(16) == 8         # capped
    assert hardware.cpu_threads(0) == 1


def test_diarize_and_whisper_threads():
    assert hardware.diarize_threads(6) == 6                 # alone: all physical cores
    assert hardware.diarize_threads(6, parallel=True) == 4  # next to a GPU transcription: two fewer
    assert hardware.diarize_threads(4, parallel=True) == 4  # small CPUs keep all of theirs
    assert hardware.diarize_threads(2) == 2 and hardware.diarize_threads(1, parallel=True) == 1
    assert hardware.diarize_threads(32) == 16
    assert hardware.whisper_threads(6) == 4 and hardware.whisper_threads(2) == 2


def test_physical_cores_fallbacks(monkeypatch):
    monkeypatch.setattr(hardware, "_physical", None)
    monkeypatch.setattr(hardware.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(hardware, "_windows_physical_cores", lambda: 6)
    assert hardware.physical_cores() == 6
    monkeypatch.setattr(hardware, "_physical", None)

    def boom():
        raise OSError("no api")

    monkeypatch.setattr(hardware, "_windows_physical_cores", boom)
    monkeypatch.setitem(sys.modules, "psutil", None)  # not installed
    assert hardware.physical_cores() == 6                 # logical // 2
    monkeypatch.setattr(hardware, "_physical", None)
    monkeypatch.setattr(hardware.os, "cpu_count", lambda: 2)
    assert hardware.physical_cores() == 2                 # tiny CPUs: do not halve
    monkeypatch.setattr(hardware, "_physical", None)
    monkeypatch.setattr(hardware.os, "cpu_count", lambda: None)
    assert hardware.physical_cores() == 1
    monkeypatch.setattr(hardware, "_physical", None)


def test_real_machine_numbers_are_sane():
    n = hardware.physical_cores()
    assert 1 <= n <= (hardware.os.cpu_count() or 1)
    assert hardware.info()["cpu"]["physical"] == n


# ---------------- judging ----------------
def test_similarity_and_garbage():
    assert tuning.similarity(SPEECH, SPEECH.upper()) == 1.0
    assert tuning.similarity(SPEECH, "hello world this is something else entirely different") < 0.2
    assert tuning.similarity("", SPEECH) == 0.0
    assert not tuning.looks_like_garbage(SPEECH)
    assert tuning.looks_like_garbage("")
    assert tuning.looks_like_garbage(" Thank you.")                      # too short to be a transcript
    assert tuning.looks_like_garbage(" ha " * 40)                         # a loop
    assert tuning.looks_like_garbage("@#$% !!! ??? ... ### %%% &&& *** +++ === ~~~")


def test_projected_rtf_spreads_model_load_over_a_part():
    assert tuning.projected_rtf(10.0, 25.0, None) == pytest.approx(0.4)
    # 25 s sample, 5 s of it was model loading: compute 0.2 + 5 s over a 300 s part
    assert tuning.projected_rtf(10.0, 25.0, 5.0) == pytest.approx(0.2 + 5 / 300)
    assert tuning.projected_rtf(10.0, 25.0, 50.0) == pytest.approx(0.4)   # nonsense load time is ignored
    assert tuning.projected_rtf(1.0, 0.0, None) == float("inf")


def run(ok=True, rtf=0.5, text=SPEECH):
    return {"ok": ok, "rtf": rtf, "text": text, "error": "" if ok else "boom"}


@pytest.mark.parametrize("cpu,vk,expect", [
    (run(rtf=0.5), run(rtf=0.2), (VULKAN, "vulkan_faster")),
    (run(rtf=0.5), run(rtf=0.5), (CPU, "cpu_faster")),
    (run(rtf=0.5), run(rtf=0.44), (CPU, "cpu_faster")),                 # inside the 15 % margin: stay on the CPU
    (run(rtf=0.5), run(rtf=0.42), (VULKAN, "vulkan_faster")),
    (run(rtf=0.5), run(ok=False), (CPU, "vulkan_failed")),
    (run(rtf=0.5), run(rtf=0.01, text=""), (CPU, "vulkan_empty_or_garbage")),
    (run(rtf=0.5), run(rtf=0.01, text=" la " * 30), (CPU, "vulkan_empty_or_garbage")),
    (run(rtf=0.5), run(rtf=0.01, text="completely unrelated english sentence about the weather today in london"),
     (CPU, "vulkan_text_differs")),
    (run(ok=False), run(rtf=0.2), (VULKAN, "cpu_failed")),
    (run(rtf=0.5, text=""), run(rtf=0.1), (CPU, "no_reference_text")),
])
def test_decide(cpu, vk, expect):
    assert tuning.decide({CPU: cpu, VULKAN: vk}) == expect


def test_decide_without_vulkan_run():
    assert tuning.decide({CPU: run()}) == (CPU, "vulkan_not_tested")


# ---------------- the self-test with fake engines ----------------
class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class Fake:
    """Engine stand-in: transcribe() advances the fake clock by `secs`, returns `text`; load/transcribe may raise."""

    def __init__(self, clock, secs=10.0, text=SPEECH, load_error=None, run_error=None, load_s=None):
        self.clock, self.secs, self.text = clock, secs, text
        self.load_error, self.run_error = load_error, run_error
        self.last_timings = {"load": load_s} if load_s is not None else {}
        self.loaded = self.runs = 0

    def load(self, model, progress=None):
        if self.load_error:
            raise self.load_error
        self.loaded += 1

    def transcribe(self, samples, duration, progress):
        self.runs += 1
        if self.run_error:
            raise self.run_error
        self.clock.t += self.secs
        return [Word(0.0, 1.0, self.text)], "tr"


SAMPLE = (np.zeros(16000 * 25, np.float32), 25.0)


def selftest(cpu, vk=None):
    clock = Clock()
    cpu_e = cpu(clock) if callable(cpu) else cpu
    f = {CPU: lambda: cpu_e}
    if vk is not None:
        vk_e = vk(clock) if callable(vk) else vk
        f[VULKAN] = lambda: vk_e
    res, kept = tuning.run_selftest("large-v3-turbo", f, SAMPLE, clock)
    return res, kept, cpu_e


def test_selftest_fast_vulkan_wins_and_cpu_model_is_released():
    res, kept, cpu_e = selftest(lambda c: Fake(c, 12.5), lambda c: Fake(c, 4.0, load_s=1.0))
    assert res["winner"] == VULKAN and res["reason"] == "vulkan_faster"
    assert res["runs"][CPU]["rtf"] == pytest.approx(0.5)
    assert res["runs"][VULKAN]["rtf"] == pytest.approx(3.0 / 25 + 1.0 / 300)
    assert res["runs"][VULKAN]["runs"] == 1       # a clear win needs no second run
    assert kept is None


def test_selftest_slow_vulkan_loses_and_cpu_engine_is_kept():
    res, kept, cpu_e = selftest(lambda c: Fake(c, 12.5), lambda c: Fake(c, 40.0))
    assert res["winner"] == CPU and res["reason"] == "cpu_faster"
    assert kept is cpu_e and cpu_e.loaded == 1    # reused for the job: no second model load
    assert res["runs"][VULKAN]["runs"] == 1       # clearly slower (>3x): no second run either


def test_selftest_borderline_vulkan_gets_a_second_run():
    clock = Clock()
    vk = Fake(clock, 11.0)
    res, kept = tuning.run_selftest("m", {CPU: lambda: Fake(clock, 12.5), VULKAN: lambda: vk}, SAMPLE, clock)
    assert vk.runs == 2 and res["runs"][VULKAN]["runs"] == 2


@pytest.mark.parametrize("vk", [
    lambda c: Fake(c, load_error=RuntimeError("Vulkan device lost")),
    lambda c: Fake(c, run_error=OSError("access violation")),
    lambda c: Fake(c, 1.0, text=""),
    lambda c: Fake(c, 1.0, text="x " * 100),
    lambda c: Fake(c, 1.0, text="this is a totally different text about something else that nobody said ever"),
])
def test_selftest_failing_or_garbage_vulkan_falls_back_to_cpu(vk):
    res, kept, cpu_e = selftest(lambda c: Fake(c, 12.5), vk)
    assert res["winner"] == CPU and kept is cpu_e
    assert res["reason"] in ("vulkan_failed", "vulkan_empty_or_garbage", "vulkan_text_differs")


def test_selftest_without_vulkan_factory():
    res, kept, cpu_e = selftest(lambda c: Fake(c, 12.5))
    assert res["winner"] == CPU and res["reason"] == "vulkan_not_tested" and kept is cpu_e


def test_selftest_cpu_failure_never_raises():
    res, kept, _ = selftest(lambda c: Fake(c, load_error=MemoryError("bad_alloc")), lambda c: Fake(c, 2.0))
    assert res["winner"] == VULKAN and res["reason"] == "cpu_failed" and kept is None
    res, kept, _ = selftest(lambda c: Fake(c, load_error=MemoryError()), lambda c: Fake(c, load_error=OSError()))
    assert res["winner"] == CPU and kept is None


def test_summary_has_no_transcripts():
    res, _, _ = selftest(lambda c: Fake(c, 12.5), lambda c: Fake(c, load_error=RuntimeError("x" * 500)))
    s = tuning.summary(res)
    assert set(s) == {CPU, VULKAN} and s[VULKAN]["rtf"] is None and len(s[VULKAN]["error"]) <= 200
    assert "text" not in s[CPU]


def test_bundled_sample_is_25_seconds_of_16k_audio():
    got = tuning.load_sample()
    assert got is not None and abs(got[1] - 25.0) < 0.01 and got[0].dtype == np.float32 and len(got[0]) == 400000
    assert tuning.load_sample(Path("does-not-exist.wav")) is None


# ---------------- fingerprint, stored verdict ----------------
def test_fingerprint_changes_with_hardware():
    a = tuning.fingerprint(hw(), "ggml-x.bin")
    assert a == tuning.fingerprint(hw(), "ggml-x.bin")
    assert a != tuning.fingerprint(hw(physical=8), "ggml-x.bin")
    assert a != tuning.fingerprint(hw(gpus=False), "ggml-x.bin")
    assert a != tuning.fingerprint(hw(), "ggml-y.bin")


def test_stored_pick_needs_same_fingerprint_and_ignores_garbage():
    fp = tuning.fingerprint(hw())
    pick = tuning.make_pick(fp, VULKAN, "vulkan_faster")
    assert tuning.stored_pick({"engine_pick": pick}, fp) == pick
    assert tuning.stored_pick({"engine_pick": pick}, fp + "x") is None        # another PC: test again
    assert tuning.stored_pick({}, fp) is None
    assert tuning.stored_pick({"engine_pick": "vulkan"}, fp) is None
    assert tuning.stored_pick({"engine_pick": dict(pick, winner="tpu")}, fp) is None


def test_old_failure_is_tested_again_but_old_success_is_kept():
    fp = tuning.fingerprint(hw())
    old = int(time.time()) - 15 * 86400
    assert tuning.stored_pick({"engine_pick": dict(tuning.make_pick(fp, CPU, "vulkan_failed"), at=old)}, fp) is None
    assert tuning.stored_pick({"engine_pick": tuning.make_pick(fp, CPU, "vulkan_failed")}, fp) is not None
    assert tuning.stored_pick({"engine_pick": dict(tuning.make_pick(fp, CPU, "cpu_faster"), at=old)}, fp) is not None


# ---------------- the plan ----------------
NOCUDA, OK = (False, "no"), (True, "")


def plan(h=None, settings=None, wcpp=OK, ggml=True, cuda=NOCUDA):
    return tuning.choose_tuned(h or hw(), settings or {}, cuda, wcpp, ggml, fp="FP")


def test_plan_target_pc_without_verdict_asks_for_selftest():
    p = plan()
    assert (p["engine"], p["device"], p["compute"]) == ("ct2", "cpu", "int8")
    assert p["selftest"] and p["reason"] == "selftest_pending" and p["threads"] == 6


def test_plan_follows_the_stored_verdict():
    p = plan(settings={"engine_pick": tuning.make_pick("FP", VULKAN, "vulkan_faster")})
    assert (p["engine"], p["device"]) == ("whispercpp", "vulkan") and not p["selftest"]
    p = plan(settings={"engine_pick": tuning.make_pick("FP", CPU, "cpu_faster")})
    assert (p["engine"], p["device"]) == ("ct2", "cpu") and not p["selftest"] and p["reason"] == "selftest_cpu"
    p = plan(settings={"engine_pick": tuning.make_pick("OTHER-PC", VULKAN, "vulkan_faster")})
    assert p["selftest"] and p["engine"] == "ct2"                              # fingerprint differs -> test again


@pytest.mark.parametrize("kw", [
    dict(h=hw(gpus=False)), dict(h=hw(vulkan=False)), dict(wcpp=(False, "no binary")), dict(ggml=False)])
def test_plan_cpu_when_vulkan_cannot_be_tried(kw):
    kw = dict(kw, settings={"engine_pick": tuning.make_pick("FP", VULKAN, "vulkan_faster")})
    p = plan(**kw)
    assert (p["engine"], p["device"], p["selftest"], p["reason"]) == ("ct2", "cpu", False, "auto_cpu")


def test_plan_prefers_working_cuda_without_selftest():
    nv = {"name": "RTX 4060", "vendor": "NVIDIA", "vram": 8 * GB, "vram_gb": 8.0, "integrated": False}
    h = hw()
    h["gpus"] = [nv]
    p = plan(h=h, cuda=OK)
    assert (p["engine"], p["device"], p["selftest"]) == ("ct2", "cuda", False)


# ---------------- ggml model lookup (the downloader's API) ----------------
def test_find_model_uses_models_ggml_path_and_tolerates_its_absence(tmp_path, monkeypatch):
    q5 = tmp_path / "ggml-large-v3-turbo-q5_0.bin"
    q5.write_bytes(b"x")
    monkeypatch.setattr(models, "ggml_path", lambda n="large-v3-turbo": q5 if n == "large-v3-turbo-q5_0" else None, raising=False)
    assert whispercpp.find_model("large-v3-turbo", True) == q5
    monkeypatch.setattr(models, "ggml_path", lambda n="large-v3-turbo": None, raising=False)
    assert whispercpp.find_model("large-v3-turbo", True) is None

    def boom(n):
        raise OSError("disk")

    monkeypatch.setattr(models, "ggml_path", boom, raising=False)
    assert whispercpp.find_model() is None
    monkeypatch.delattr(models, "ggml_path")                  # the helper does not exist yet: Vulkan not available
    assert whispercpp.find_model() is None


def test_big_ggml_file_only_for_real_graphics_cards():
    assert whispercpp.ggml_candidates(True) == ("large-v3-turbo-q5_0",)
    assert whispercpp.ggml_candidates(False)[-1] == "large-v3-turbo"


def test_parse_timings():
    lines = ["whisper_print_timings:     load time =   551.31 ms", "x", "whisper_print_timings:    total time =  6421.30 ms"]
    assert whispercpp.parse_timings(lines) == {"load": pytest.approx(0.55131), "total": pytest.approx(6.4213)}
    assert whispercpp.parse_timings(["nothing"]) == {}


# ---------------- asr: first use, remembering, fallbacks ----------------
class FakeEngine:
    def __init__(self, name, device, load_error=None, run_error=None):
        self.name, self.device, self.error = name, device, None
        self.load_error, self.run_error, self.loaded = load_error, run_error, 0

    def load(self, model, progress=None):
        if self.load_error:
            raise self.load_error
        self.loaded = 1  # like CT2Engine.load: loading twice is a no-op

    def transcribe(self, samples, duration, progress):
        if self.run_error:
            raise self.run_error
        return [Word(0.0, 1.0, " merhaba")], "tr"


@pytest.fixture
def target_pc(monkeypatch):
    """asr sees the target PC: onboard Radeon, whisper.cpp present, ggml file downloaded, no CUDA."""
    from backend import engines

    monkeypatch.setattr(hardware, "info", lambda refresh=False: hw())
    monkeypatch.setattr(engines, "wcpp_available", lambda: (True, "AMD Radeon(TM) Graphics"))
    monkeypatch.setattr(engines, "cuda_status", lambda: (False, "no"))
    monkeypatch.setattr(whispercpp, "find_model", lambda m="large-v3-turbo", integrated=True: Path("ggml-large-v3-turbo-q5_0.bin"))
    made = []

    def create(p):
        e = FakeEngine(p["engine"], p["device"])
        made.append((p["engine"], p["device"], e))
        return e

    monkeypatch.setattr(engines, "create", create)
    return made


def fake_selftest(monkeypatch, winner, reason, kept=None):
    calls = []

    def run(model, factories, sample, clock=None):
        calls.append(sorted(factories))
        return {"winner": winner, "reason": reason,
                "runs": {CPU: run_ok(0.5), VULKAN: run_ok(0.2)}}, kept

    monkeypatch.setattr(tuning, "run_selftest", run)
    return calls


def run_ok(rtf):
    return {"ok": True, "rtf": rtf, "text": SPEECH, "error": ""}


def test_first_use_runs_the_selftest_once_and_remembers_vulkan(target_pc, monkeypatch):
    calls = fake_selftest(monkeypatch, VULKAN, "vulkan_faster")
    notes = []
    eng = asr.load_model(note=notes.append)
    assert (eng.name, eng.device) == ("whispercpp", "vulkan")
    assert notes == [tuning.NOTE_SELFTEST, None] and calls == [[CPU, VULKAN]]
    pick = asr.get_settings()["engine_pick"]
    assert pick["winner"] == VULKAN and pick["runs"][CPU]["rtf"] == 0.5 and "text" not in pick["runs"][CPU]
    assert asr.status()["engine_in_use"] == "whispercpp" and asr.key().startswith("whispercpp/vulkan/")
    asr.release()
    notes.clear()
    asr.load_model(note=notes.append)                       # second start: remembered, no test, no note
    assert len(calls) == 1 and notes == []


def test_cpu_winner_reuses_the_engine_the_test_already_loaded(target_pc, monkeypatch):
    kept = FakeEngine("ct2", "cpu")
    kept.loaded = 1
    fake_selftest(monkeypatch, CPU, "cpu_faster", kept=kept)
    assert asr.load_model() is kept and kept.loaded == 1
    assert target_pc == []                                  # nothing else was created


def test_selftest_crash_still_gives_a_working_cpu_engine(target_pc, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("test blew up")

    monkeypatch.setattr(tuning, "run_selftest", boom)
    eng = asr.load_model()
    assert (eng.name, eng.device) == ("ct2", "cpu")
    assert asr.get_settings()["engine_pick"]["reason"] == "selftest_error"


def test_vulkan_engine_that_cannot_load_falls_back_to_cpu(target_pc, monkeypatch):
    from backend import engines

    asr.set_setting("engine_pick", tuning.make_pick(tuning.fingerprint(hw(), "ggml-large-v3-turbo-q5_0.bin"), VULKAN, "vulkan_faster"))

    def create(p):
        return FakeEngine(p["engine"], p["device"],
                          load_error=whispercpp.WhisperCppError("driver gone") if p["engine"] == "whispercpp" else None)

    monkeypatch.setattr(engines, "create", create)
    eng = asr.load_model()
    assert (eng.name, eng.device) == ("ct2", "cpu")
    assert asr.get_settings()["engine_pick"]["reason"] == "runtime_failure"
    assert asr.plan()["engine"] == "ct2" and not asr.plan()["selftest"]   # remembered, no endless retrying


def test_vulkan_failure_in_the_middle_of_a_job_is_retried_on_cpu(target_pc, monkeypatch):
    from backend import engines

    asr.set_setting("engine_pick", tuning.make_pick(tuning.fingerprint(hw(), "ggml-large-v3-turbo-q5_0.bin"), VULKAN, "vulkan_faster"))

    def create(p):
        if p["engine"] == "whispercpp":
            return FakeEngine("whispercpp", "vulkan", run_error=whispercpp.WhisperCppError("exit 3"))
        return FakeEngine("ct2", "cpu")

    monkeypatch.setattr(engines, "create", create)
    words, lang = asr.transcribe(np.zeros(16000, np.float32), 1.0, lambda p: None)
    assert [w.text for w in words] == [" merhaba"] and lang == "tr"
    assert asr.get_settings()["engine_pick"]["winner"] == CPU


def test_a_stop_request_is_not_mistaken_for_an_engine_failure(target_pc, monkeypatch):
    from backend import engines

    class Stop(Exception):
        pass

    asr.set_setting("engine_pick", tuning.make_pick(tuning.fingerprint(hw(), "ggml-large-v3-turbo-q5_0.bin"), VULKAN, "vulkan_faster"))
    monkeypatch.setattr(engines, "create", lambda p: FakeEngine(p["engine"], p["device"], run_error=Stop()))
    with pytest.raises(Stop):
        asr.transcribe(np.zeros(16000, np.float32), 1.0, lambda p: None)
    assert asr.get_settings()["engine_pick"]["winner"] == VULKAN     # not blamed on Vulkan


def test_pc_without_vulkan_never_runs_a_selftest(monkeypatch):
    from backend import engines

    monkeypatch.setattr(hardware, "info", lambda refresh=False: hw(gpus=False))
    monkeypatch.setattr(engines, "cuda_status", lambda: (False, "no"))
    monkeypatch.setattr(engines, "create", lambda p: FakeEngine(p["engine"], p["device"]))
    monkeypatch.setattr(tuning, "run_selftest", lambda *a, **k: pytest.fail("no test expected"))
    eng = asr.load_model()
    assert (eng.name, eng.device) == ("ct2", "cpu") and "engine_pick" not in asr.get_settings()
