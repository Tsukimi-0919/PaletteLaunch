"""src/core/single_instance.py のテスト（Phase 6: アプリの二重起動防止）。win32 はモックする。"""
import os
import sys
from unittest import mock

import pytest

from src.core import single_instance as si

APP = os.path.normcase(os.path.realpath("C:\\Apps\\PaletteLaunch\\PaletteLaunch.exe"))


@pytest.fixture
def win32(monkeypatch):
    mods = {name: mock.MagicMock() for name in
            ("win32api", "win32event", "win32gui", "win32process", "win32security")}
    for name, module in mods.items():
        monkeypatch.setitem(sys.modules, name, module)
    return mock.NonCallableMock(**mods)


# --- ミューテックス -----------------------------------------------------------

def test_mutex_name_is_local_and_per_user():
    a = si.mutex_name("S-1-5-21-111-1001")
    b = si.mutex_name("S-1-5-21-111-1002")
    assert a.startswith("Local\\")
    assert a != b
    assert "S-1-5-21-111-1001" in a


def test_mutex_name_has_no_backslash_after_prefix():
    name = si.mutex_name("DOMAIN\\user name")
    assert name.startswith("Local\\")
    assert "\\" not in name[len("Local\\"):]


def test_mutex_name_uses_sid(win32):
    win32.win32security.ConvertSidToStringSid.return_value = "S-1-5-21-9-9-9-1001"
    assert si.mutex_name().endswith("S-1-5-21-9-9-9-1001")


def test_mutex_name_falls_back_to_user_name(win32, monkeypatch):
    win32.win32security.OpenProcessToken.side_effect = OSError("denied")
    monkeypatch.setattr(si.getpass, "getuser", lambda: "alice")
    assert si.mutex_name().endswith("alice")


def test_acquire_first_instance(win32):
    win32.win32api.GetLastError.return_value = 0
    handle = si.acquire("Local\\Test")
    assert handle is win32.win32event.CreateMutex.return_value
    win32.win32event.CreateMutex.assert_called_once_with(None, False, "Local\\Test")


def test_acquire_second_instance(win32):
    win32.win32api.GetLastError.return_value = 183  # ERROR_ALREADY_EXISTS
    assert si.acquire("Local\\Test") is None
    win32.win32api.CloseHandle.assert_called_once()


def test_acquire_failure_does_not_block_start(win32):
    win32.win32event.CreateMutex.side_effect = OSError("x")
    assert si.acquire("Local\\Test") == ""


# --- 起動済みウィンドウの前面表示 ---------------------------------------------

def test_activates_only_window_of_same_executable(win32):
    windows = [(1, 100), (2, 200)]  # 1: エクスプローラーの「PaletteLaunch」フォルダ、2: 本物
    images = {100: "C:\\Windows\\explorer.exe", 200: "C:\\Apps\\PaletteLaunch\\PaletteLaunch.exe"}
    win32.win32gui.IsIconic.return_value = False
    assert si.activate_existing(find_windows=lambda t: windows, image_path=images.get,
                                allowed={APP}) is True
    win32.win32gui.SetForegroundWindow.assert_called_once_with(2)


def test_explorer_window_is_not_activated(win32):
    windows = [(1, 100)]
    assert si.activate_existing(find_windows=lambda t: windows,
                                image_path=lambda pid: "C:\\Windows\\explorer.exe",
                                allowed={APP}) is False
    win32.win32gui.SetForegroundWindow.assert_not_called()
    win32.win32gui.ShowWindow.assert_not_called()


def test_unknown_process_is_not_activated(win32):
    """プロセスの実行ファイルを確認できなければ何もしない"""
    assert si.activate_existing(find_windows=lambda t: [(1, 100)], image_path=lambda pid: None,
                                allowed={APP}) is False
    win32.win32gui.SetForegroundWindow.assert_not_called()


def test_minimized_window_is_restored(win32):
    win32.win32gui.IsIconic.return_value = True
    si.activate_existing(find_windows=lambda t: [(5, 1)],
                         image_path=lambda pid: "C:\\Apps\\PaletteLaunch\\PaletteLaunch.exe",
                         allowed={APP})
    win32.win32gui.ShowWindow.assert_called_once_with(5, si._SW_RESTORE)


def test_activation_error_is_swallowed(win32):
    def boom(title):
        raise OSError("x")
    assert si.activate_existing(find_windows=boom, allowed={APP}) is False


def test_window_search_uses_title(win32):
    seen = []
    si.activate_existing(find_windows=lambda t: seen.append(t) or [],
                         image_path=lambda pid: None, allowed={APP})
    assert seen == [si.WINDOW_TITLE]


def test_expected_executables_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\Apps\\PaletteLaunch\\PaletteLaunch.exe")
    assert si.expected_executables() == {APP}


def test_expected_executables_dev_includes_base_python(monkeypatch):
    """venv の python.exe は元の python.exe を起動するため、両方を認める"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\proj\\.venv\\Scripts\\python.exe")
    monkeypatch.setattr(sys, "_base_executable", "C:\\Python312\\python.exe", raising=False)
    result = si.expected_executables()
    assert os.path.normcase(os.path.realpath("C:\\proj\\.venv\\Scripts\\python.exe")) in result
    assert os.path.normcase(os.path.realpath("C:\\Python312\\python.exe")) in result


def test_flashes_when_foreground_is_refused(win32):
    win32.win32gui.IsIconic.return_value = False
    win32.win32gui.SetForegroundWindow.side_effect = OSError("refused")
    assert si.activate_existing(find_windows=lambda t: [(7, 1)],
                                image_path=lambda pid: "C:\Apps\PaletteLaunch\PaletteLaunch.exe",
                                allowed={APP}) is True
    win32.win32gui.FlashWindow.assert_called_once_with(7, True)
