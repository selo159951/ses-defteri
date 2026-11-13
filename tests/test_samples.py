"""The two bundled sample recordings are started once, on the very first start."""
from backend import bridge, pipeline


def test_samples_start_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))
    started = []
    api = bridge.Api(lambda: None)
    monkeypatch.setattr(api, "start_jobs", lambda paths: [started.append(p) or {"id": None, "filename": p} for p in paths])
    api.start_samples_once()
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in started] == ["ornek-uc-kisi.wav", "ornek-tek-kisi.wav"]
    assert api.start_samples_once() == [] and len(started) == 2


def test_sample_files_are_in_assets():
    d = bridge.Api._samples_dir()
    assert all((d / f).is_file() for f, _ in bridge.Api.SAMPLES)
