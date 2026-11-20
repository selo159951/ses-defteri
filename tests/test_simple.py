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


# ---------------- ported features: options popup, Word button, one person's lines, icon, noise model ----------------
def _frontend(name):
    return (ROOT / "frontend" / name).read_text("utf-8")


def test_every_id_used_by_app_js_exists_in_the_page():
    html = _frontend("index.html")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    used = set(re.findall(r'\$\("([A-Za-z][\w-]*)"\)', _frontend("app.js")))
    # ids made at run time are created by the scripts themselves
    missing = {i for i in used - ids if i not in ("tourBtn",)}
    assert not missing, missing


def test_options_popup_holds_folder_watch_and_noise_settings():
    html = _frontend("index.html")
    box = html[html.index('id="optsBox"'):html.index('id="watchInd"')]
    for el_id in ("optsClose", "denoiseMode", "denoiseAsk", "dnReset", "watchOn", "watchPick"):
        assert f'id="{el_id}"' in box, el_id
    assert 'id="optsSum"' in box
    js = _frontend("app.js")
    assert "Escape" in js and "e.target === box" in js  # Esc and a click on the backdrop close it
    assert 'watchOn" checked' not in html  # folder watch is off until the user switches it on


def test_word_button_and_one_person_export_are_wired():
    html, js = _frontend("index.html"), _frontend("app.js")
    assert 'id="wordBtn"' in html and 'id="expWhoList"' in html
    assert 'call("save_word"' in js and "exportOnly" in js
    css = _frontend("simple.css")
    assert "#view .spkbtns" in css and "#view .spkmore," not in css  # the "..." menu is shown, with one item


def test_new_texts_exist_in_turkish_and_have_no_emoji():
    js = _frontend("simple.js")
    tr = js[js.index("Object.assign(I18N.tr, {\n  options"):js.index("Object.assign(I18N.en, {\n  options")]
    for key in ("options", "opts_on", "save_word", "only_export", "watch_on", "denoise_label", "ab_title", "dn_reset"):
        assert re.search(rf"\b{key}:", tr), key
    for name in ("simple.js", "simple.css", "index.html", "app.js", "simple-progress.js"):
        text = _frontend(name)
        assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", text), name


def test_app_icon_is_in_the_page_and_the_exe():
    html = _frontend("index.html")
    assert html.count('src="icon.svg"') >= 3  # header, about, empty list
    assert html.count('src="loading.svg"') >= 2  # animated microphone: opening screen, progress box
    assert (ROOT / "frontend" / "icon.svg").is_file() and (ROOT / "frontend" / "loading.svg").is_file()
    assert (ROOT / "assets" / "icon.ico").is_file()
    assert 'icon="assets/icon.ico"' in (ROOT / "SesDefteri.spec").read_text("utf-8")


def test_noise_model_ships_with_the_package_and_nothing_is_downloaded_for_it():
    assert "gtcrn_simple.onnx" in (ROOT / "fetch_models.py").read_text("utf-8")
    src = (ROOT / "backend" / "denoise.py").read_text("utf-8")
    assert "urllib" not in src and "requests" not in src
    spec = (ROOT / "SesDefteri.spec").read_text("utf-8")
    assert 'for n in os.listdir("models")' in spec  # every file in models/ (including the denoiser) is bundled
