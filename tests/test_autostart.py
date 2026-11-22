"""Start with Windows: the Run value and --tray."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import autostart  # noqa: E402


class FakeReg:
    """Just enough of winreg for the Run key, so the test runs on any system."""
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.keys = {}

    def OpenKey(self, _hive, path, _res=0, _access=0):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return path

    def CreateKeyEx(self, _hive, path, _res=0, _access=0):
        self.keys.setdefault(path, {})
        return path

    def QueryValueEx(self, key, name):
        values = self.keys.get(key, {})
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], self.REG_SZ

    def SetValueEx(self, key, name, _res, _type, value):
        self.keys.setdefault(key, {})[name] = value

    def DeleteValue(self, key, name):
        if name not in self.keys.get(key, {}):
            raise FileNotFoundError(name)
        del self.keys[key][name]

    def CloseKey(self, _key):
        pass


def test_command_points_at_the_exe_with_tray():
    assert autostart.command(r"C:\Apps\SesDefteri.exe") == r'"C:\Apps\SesDefteri.exe" --tray'


def test_started_in_tray():
    assert autostart.started_in_tray(["app.py", "--tray"]) is True
    assert autostart.started_in_tray(["app.py"]) is False


def test_enable_and_disable_round_trip():
    reg = FakeReg()
    assert autostart.enabled(reg) is False
    assert autostart.set_enabled(True, reg, exe=r"C:\Apps\SesDefteri.exe") is True
    assert autostart.enabled(reg) is True
    assert reg.keys[autostart.RUN_KEY][autostart.VALUE] == r'"C:\Apps\SesDefteri.exe" --tray'
    assert autostart.set_enabled(False, reg) is True
    assert autostart.enabled(reg) is False


def test_disable_without_existing_value_is_harmless():
    assert autostart.set_enabled(False, FakeReg()) is True


def test_missing_registry_module_never_raises():
    assert autostart.enabled(reg=None) in (True, False)
