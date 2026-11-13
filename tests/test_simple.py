"""Tests for what makes the simple edition simple: fixed data folder, fixed settings, bundled model, slim frontend."""
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALL_HOME_ENVS = ("SESDEFTERIBASIT_HOME", "SESDEFTERI_HOME", "KATIP_HOME", "MEETTRANSCRIBER_HOME")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for k in ALL_HOME_ENVS:
        monkeypatch.delenv(k, raising=False)
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata


def test_data_dir_defaults_to_appdata_sesdefteribasit(clean_env):
    from backend import store

    if os.name != "nt":
        pytest.skip("APPDATA is only used on Windows")
    assert store.data_dir() == clean_env / "SesDefteriBasit"
    assert (clean_env / "SesDefteriBasit").is_dir()


def test_data_dir_honours_only_sesdefteribasit_home(clean_env, monkeypatch, tmp_path):
    from backend import store

    for k in ("SESDEFTERI_HOME", "KATIP_HOME"):
        monkeypatch.setenv(k, str(tmp_path / "other" / k))
    if os.name == "nt":
        assert store.data_dir() == clean_env / "SesDefteriBasit"  # the other names are ignored
    assert not (tmp_path / "other").exists()
    mine = tmp_path / "mine"
    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(mine))
    assert store.data_dir() == mine and mine.is_dir()


def test_migrate_old_data_does_nothing(clean_env):
    from backend import store

    for old in ("Katip", "SesDefteri"):
        d = clean_env / old
        d.mkdir()
        (d / "keep.txt").write_text(old, "utf-8")
    before = sorted(p.name for p in clean_env.iterdir())
    assert store.migrate_old_data() is False
    assert sorted(p.name for p in clean_env.iterdir()) == before
    for old in ("Katip", "SesDefteri"):
        assert (clean_env / old / "keep.txt").read_text("utf-8") == old
    assert not (clean_env / "SesDefteriBasit").exists()


def test_settings_are_forced(monkeypatch, tmp_path):
    from backend import asr

    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))
    asr.set_setting("language", "mixed")
    asr.set_setting("meeting_mode", True)
    asr.set_setting("learn_people", True)
    asr.set_setting("model", "large-v3")
    asr.set_setting("engine", "ct2-cpu")
    asr.set_setting("ui_lang", "en")
    s = asr.get_settings()
    assert s["model"] == "large-v3-turbo"
    assert s["engine"] == "auto"
    assert s["language"] == "auto"
    assert s["meeting_mode"] is False
    assert s["learn_people"] is False
    assert s["ui_lang"] == "tr"


def test_bundled_model_is_found(monkeypatch, tmp_path):
    from backend import models

    monkeypatch.setenv("SESDEFTERIBASIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SESDEFTERI_MODEL_DIR", str(tmp_path / "empty-models"))
    model = ROOT / "models" / "whisper-large-v3-turbo"
    if not (model / "model.bin").is_file():
        pytest.skip("bundled model is not in this checkout")
    assert models.bundled() == model
    assert models.bundled("large-v3") is None
    assert models.is_downloaded("large-v3-turbo") is True


def test_frontend_loads_simple_scripts_only():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    scripts = re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)
    assert "simple.js" in scripts and "app.js" in scripts
    assert scripts.index("simple.js") < scripts.index("app.js")
    for gone in ("system.js", "people.js", "analysis.js", "tour.js"):
        assert gone not in scripts
    assert "simple.css" in html


def test_pipeline_does_not_import_removed_modules():
    src = (ROOT / "backend" / "pipeline.py").read_text("utf-8")
    for mod in ("glossary", "names", "people", "analysis"):
        assert not re.search(rf"^\s*(from\s+(backend\.|\.)?{mod}\b|import\s+(backend\.)?{mod}\b|from\s+(backend|\.)\s+import\s+[^\n]*\b{mod}\b)", src, re.M), mod
