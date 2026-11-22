"""Meeting detection from a fake copy of the microphone consent store (no registry needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import meeting_detect as md  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


def test_teams_using_the_microphone_now():
    usage = {r"C:\Users\me\AppData\Local\Microsoft\Teams\ms-teams.exe": 0}
    assert md.detect(usage)["app"] == "Teams"


def test_an_app_that_let_go_is_not_detected():
    usage = {"Zoom.exe": 1700000000}  # LastUsedTimeStop is a timestamp, not 0
    assert md.detect(usage) is None


def test_browser_means_meet():
    assert md.label_for(r"C:\Program Files\Google\Chrome\Application\chrome.exe") == "Meet"
    assert md.label_for("msedge.exe") == "Meet"
    assert md.label_for("firefox.exe") == "Meet"


def test_other_apps_are_ignored():
    assert md.label_for(r"C:\Windows\System32\audiodg.exe") is None
    assert md.detect({"SomethingElse.exe": 0}) is None


def test_our_own_process_is_ignored():
    usage = {r"C:\Apps\SesDefteri.exe": 0}
    assert md.detect(usage, ignore=("sesdefteri",)) is None
    assert md.detect(usage, ignore=()) is None  # not a meeting app either way


def test_non_packaged_path_with_hash():
    assert md.label_for("C:#Program Files#Zoom#bin#Zoom.exe") == "Zoom"


def test_unknown_stop_values_do_not_crash():
    assert md.detect({"Zoom.exe": "nonsense", "Teams.exe": 0})["app"] == "Teams"


def test_detector_polls_the_reader():
    state = {"usage": {"Slack.exe": 0}}
    d = md.Detector(interval=999, reader=lambda: state["usage"], ignore=())
    assert d.poll()["active"] is True and d.poll()["app"] == "Slack"
    state["usage"] = {"Slack.exe": 123}
    assert d.poll() == {"active": False, "app": None, "name": None}


def test_detector_survives_a_reader_error():
    def boom():
        raise OSError("registry unavailable")

    d = md.Detector(interval=999, reader=boom)
    assert d.poll() == {"active": False, "app": None, "name": None}


def test_bridge_status_follows_the_setting():
    from backend.bridge import Api

    api = Api(window_getter=lambda: None)
    assert api.meeting_detect_status()["enabled"] is True  # on by default
    api.set_settings({"meeting_suggest": False})
    st = api.meeting_detect_status()
    assert st["enabled"] is False and st["active"] is False and st["recording"] is False
