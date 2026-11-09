"""src/core/single_instance.py のテスト（Phase 6: アプリの二重起動防止）。

Win32 の呼び出しは FakeWin32 に差し替える。記録ファイルは tmp_path に作る。
"""
import json
import logging
import sys
import time
from unittest import mock

import pytest

from src.core import single_instance as si

PID, HWND = 4242, 0x1234


class FakeWin32:
    """Win32 の代わり。windows: {hwnd: (pid, title)}"""

    def __init__(self, windows=None):
        self.windows = dict(windows or {})
        self.foreground = 0
        self.iconic = set()
        self.zoomed = set()
        self.restore_to_max = set()
        self.calls = []
        self.allow_result = (True, 0)
        self.set_foreground_ok = True
        self.events = {}
        self.created = []

    def last_error(self):
        return 0

    def is_window(self, hwnd):
        return hwnd in self.windows

    def window_pid(self, hwnd):
        return self.windows.get(hwnd, (0, ""))[0]

    def window_text(self, hwnd):
        return self.windows.get(hwnd, (0, ""))[1]

    def find_windows(self, pid, title):
        return [h for h, (p, t) in self.windows.items() if p == pid and t == title]

    def is_iconic(self, hwnd):
        return hwnd in self.iconic

    def is_zoomed(self, hwnd):
        return hwnd in self.zoomed

    def restores_to_maximized(self, hwnd):
        return hwnd in self.restore_to_max

    def set_foreground(self, hwnd):
        self.calls.append(("set_foreground", hwnd))
        if self.set_foreground_ok:
            self.foreground = hwnd
            return True, 0
        return False, 5

    def foreground_window(self):
        return self.foreground

    def allow_set_foreground(self, pid):
        self.calls.append(("allow", pid))
        return self.allow_result

    def flash(self, hwnd):
        self.calls.append(("flash", hwnd))

    def create_event(self, name):
        self.created.append(name)
        self.events[name] = handle = mock.sentinel.event
        return handle

    def open_event(self, name):
        return (self.events.get(name), 0 if name in self.events else 2)

    def set_event(self, handle):
        self.calls.append(("set_event", handle))
        return True

    def wait(self, handle, timeout_ms):
        time.sleep(0.01)  # 空回りしないように少し待つ（依頼は来ない）
        return False

    def close(self, handle):
        pass


class FakeWindow:
    """pywebview のウィンドウの代わり。win32 の状態を pywebview と同じように変える"""

    def __init__(self, win32, hwnd=HWND, show_activates=True, restore_activates=True):
        self.win32, self.hwnd = win32, hwnd
        self.show_activates = show_activates
        self.restore_activates = restore_activates
        self.calls = []

    def restore(self):
        self.calls.append("restore")
        self.win32.iconic.discard(self.hwnd)
        self.win32.zoomed.discard(self.hwnd)
        if self.restore_activates:
            self.win32.foreground = self.hwnd

    def maximize(self):
        self.calls.append("maximize")
        self.win32.iconic.discard(self.hwnd)
        self.win32.zoomed.add(self.hwnd)
        if self.restore_activates:
            self.win32.foreground = self.hwnd

    def minimize(self):
        self.calls.append("minimize")
        if self.hwnd in self.win32.zoomed:
            self.win32.restore_to_max.add(self.hwnd)
        self.win32.iconic.add(self.hwnd)

    def show(self):
        self.calls.append("show")
        if self.show_activates:
            self.win32.foreground = self.hwnd


@pytest.fixture
def record(tmp_path):
    return str(tmp_path / "PaletteLaunch" / "instance.json")


def run_activate(record, win32, **kw):
    kw.setdefault("record_wait", 0)
    kw.setdefault("activate_wait", 0)
    return si.activate_existing(path=record, win32=win32, event_name="Local\\Test", **kw)


# --- 名前 ---------------------------------------------------------------------

def test_mutex_name_is_local_and_per_user():
    a = si.mutex_name("S-1-5-21-111-1001")
    b = si.mutex_name("S-1-5-21-111-1002")
    assert a.startswith("Local\\")
    assert a != b
    assert "S-1-5-21-111-1001" in a


def test_event_name_is_local_and_per_user():
    assert si.activate_event_name("S-1-5-21-1").startswith("Local\\")
    assert si.activate_event_name("S-1-5-21-1") != si.activate_event_name("S-1-5-21-2")
    assert si.activate_event_name("S-1") != si.mutex_name("S-1")


def test_mutex_name_has_no_backslash_after_prefix():
    name = si.mutex_name("DOMAIN\\user name")
    assert name.startswith("Local\\")
    assert "\\" not in name[len("Local\\"):]


def test_instance_file_is_in_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert si.default_instance_file() == str(tmp_path / "PaletteLaunch" / "instance.json")


# --- ミューテックス -----------------------------------------------------------

@pytest.fixture
def win32mods(monkeypatch):
    mods = {name: mock.MagicMock() for name in ("win32api", "win32event", "win32security")}
    for name, module in mods.items():
        monkeypatch.setitem(sys.modules, name, module)
    return mock.NonCallableMock(**mods)


def test_mutex_name_uses_sid(win32mods):
    win32mods.win32security.ConvertSidToStringSid.return_value = "S-1-5-21-9-9-9-1001"
    assert si.mutex_name().endswith("S-1-5-21-9-9-9-1001")


def test_mutex_name_falls_back_to_user_name(win32mods, monkeypatch):
    win32mods.win32security.OpenProcessToken.side_effect = OSError("denied")
    monkeypatch.setattr(si.getpass, "getuser", lambda: "alice")
    assert si.mutex_name().endswith("alice")


def test_acquire_first_instance(win32mods):
    win32mods.win32api.GetLastError.return_value = 0
    assert si.acquire("Local\\Test") is win32mods.win32event.CreateMutex.return_value
    win32mods.win32event.CreateMutex.assert_called_once_with(None, False, "Local\\Test")


def test_acquire_second_instance(win32mods):
    win32mods.win32api.GetLastError.return_value = 183  # ERROR_ALREADY_EXISTS
    assert si.acquire("Local\\Test") is None
    win32mods.win32api.CloseHandle.assert_called_once()


def test_acquire_failure_does_not_block_start(win32mods):
    win32mods.win32event.CreateMutex.side_effect = OSError("x")
    assert si.acquire("Local\\Test") == ""


# --- 記録ファイル ---------------------------------------------------------------

def test_record_roundtrip_and_remove(record):
    si.write_record(record, PID, HWND)
    assert si.read_record(record) == {"pid": PID, "hwnd": HWND}
    si.remove_record(record, PID + 1)  # 他人の記録は消さない
    assert si.read_record(record) is not None
    si.remove_record(record, PID)
    assert si.read_record(record) is None


@pytest.mark.parametrize("content", [
    "not json", "[]", '{"pid": "1", "hwnd": 2}', '{"pid": 1}', '{"pid": 0, "hwnd": 2}',
    '{"pid": true, "hwnd": 2}', '{"pid": 1, "hwnd": -5}',
])
def test_bad_record_is_ignored(record, content):
    import os
    os.makedirs(os.path.dirname(record), exist_ok=True)
    with open(record, "w", encoding="utf-8") as f:
        f.write(content)
    assert si.read_record(record) is None


# --- 1つ目: 記録と前面化の依頼の受け取り -----------------------------------------

def test_host_publishes_own_window(record):
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE), 0x999: (PID + 1, si.WINDOW_TITLE)})
    host = si.InstanceHost(path=record, win32=win32, pid=PID, event_name="Local\\Test")
    assert host.publish(attempts=1, interval=0) is True
    assert json.load(open(record, encoding="utf-8"))["hwnd"] == HWND
    assert win32.created == ["Local\\Test"]
    host.close()
    assert si.read_record(record) is None


def test_host_without_window_does_not_record(record, caplog):
    host = si.InstanceHost(path=record, win32=FakeWin32(), pid=PID, event_name="Local\\Test")
    with caplog.at_level(logging.WARNING):
        assert host.publish(attempts=2, interval=0) is False
    assert si.read_record(record) is None
    assert "自分のウィンドウが見つからない" in caplog.text


def make_host(record, win32, window):
    host = si.InstanceHost(window, path=record, win32=win32, pid=PID, event_name="Local\\Test")
    assert host.publish(attempts=1, interval=0)
    return host


@pytest.fixture
def no_settle(monkeypatch):
    monkeypatch.setattr(si.time, "sleep", lambda s: None)


def test_host_restores_minimized_window_with_pywebview(record, no_settle):
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    win32.iconic.add(HWND)
    window = FakeWindow(win32)
    host = make_host(record, win32, window)
    try:
        assert host.bring_to_front() is True
        assert window.calls == ["restore", "show"]
    finally:
        host.close()


def test_host_returns_to_maximized(record, no_settle):
    """最大化から最小化したウィンドウは、最大化に戻す"""
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    win32.iconic.add(HWND)
    win32.restore_to_max.add(HWND)
    window = FakeWindow(win32)
    host = make_host(record, win32, window)
    try:
        assert host.bring_to_front() is True
        assert window.calls == ["maximize", "show"]
        assert HWND in win32.zoomed
    finally:
        host.close()


def test_host_behind_window_is_shown(record, no_settle):
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    window = FakeWindow(win32)
    host = make_host(record, win32, window)
    try:
        assert host.bring_to_front() is True
        assert window.calls == ["show"]
    finally:
        host.close()


@pytest.mark.parametrize("zoomed,expected", [(False, "restore"), (True, "maximize")])
def test_host_falls_back_to_minimize_restore(record, no_settle, zoomed, expected):
    """前面化の権限が無く show で前に出ないときは、pywebview の API で最小化 → 復元する"""
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    if zoomed:
        win32.zoomed.add(HWND)
    window = FakeWindow(win32, show_activates=False)
    host = make_host(record, win32, window)
    try:
        assert host.bring_to_front() is True
        assert window.calls == ["show", "minimize", expected, "show"]
    finally:
        host.close()


def test_host_without_pywebview_window_does_nothing(record, caplog):
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    host = make_host(record, win32, None)
    try:
        with caplog.at_level(logging.WARNING):
            assert host.bring_to_front() is False
        assert "pywebview のウィンドウが無い" in caplog.text
    finally:
        host.close()


def test_state_changes_do_not_use_win32_show_window():
    """Win32 の ShowWindow で復元すると WebView2 が描画されなくなる（別スレッドから呼んだ場合）。
    状態の変更は pywebview の API だけで行う"""
    source = open(si.__file__, encoding="utf-8").read()
    assert "user32.ShowWindow" not in source
    assert "ShowWindowAsync" not in source
    assert not hasattr(si.Win32, "restore") and not hasattr(si.Win32, "minimize")


# --- 2つ目: 起動済みのウィンドウを前面に出す ---------------------------------------

def test_activates_recorded_window(record, caplog):
    si.write_record(record, PID, HWND)
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    win32.events["Local\\Test"] = mock.sentinel.event
    win32.foreground = HWND  # 1つ目が依頼を受けて前面に出た
    with caplog.at_level(logging.INFO):
        assert run_activate(record, win32, activate_wait=0.5) is True
    assert ("allow", PID) in win32.calls
    assert ("set_event", mock.sentinel.event) in win32.calls
    for text in ("記録を読みました", "PID 一致", "AllowSetForegroundWindow", "前面化を依頼しました",
                 "前面に出ました"):
        assert text in caplog.text, text


def test_missing_record_is_logged(record, caplog):
    with caplog.at_level(logging.WARNING):
        assert run_activate(record, FakeWin32()) is False
    assert "記録が見つかりません" in caplog.text


def test_waits_for_record(record, monkeypatch):
    """1つ目がまだ起動中で記録が無いときは、記録ができるまで待つ"""
    calls = []

    def fake_read(path):
        calls.append(path)
        return {"pid": PID, "hwnd": HWND} if len(calls) >= 3 else None

    monkeypatch.setattr(si, "read_record", fake_read)
    monkeypatch.setattr(si.time, "sleep", lambda s: None)
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    win32.foreground = HWND
    assert run_activate(record, win32, record_wait=5) is True
    assert len(calls) == 3


def test_stale_window_is_not_touched(record, caplog):
    si.write_record(record, PID, HWND)
    win32 = FakeWin32()
    with caplog.at_level(logging.WARNING):
        assert run_activate(record, win32) is False
    assert "ありません" in caplog.text
    assert win32.calls == []


def test_pid_mismatch_is_not_touched(record, caplog):
    """記録のウィンドウが別のプロセス（例: エクスプローラーの PaletteLaunch フォルダ）のもの"""
    si.write_record(record, PID, HWND)
    win32 = FakeWin32({HWND: (999, si.WINDOW_TITLE)})
    with caplog.at_level(logging.WARNING):
        assert run_activate(record, win32) is False
    assert "PID が一致しません" in caplog.text
    assert win32.calls == []


def test_title_mismatch_is_not_touched(record, caplog):
    si.write_record(record, PID, HWND)
    win32 = FakeWin32({HWND: (PID, "Notepad")})
    with caplog.at_level(logging.WARNING):
        assert run_activate(record, win32) is False
    assert "タイトルが一致しません" in caplog.text
    assert win32.calls == []


def test_second_tries_itself_then_flashes(record, caplog):
    si.write_record(record, PID, HWND)
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    win32.allow_result = (False, 5)
    win32.set_foreground_ok = False
    with caplog.at_level(logging.INFO):
        assert run_activate(record, win32) is False
    assert ("set_foreground", HWND) in win32.calls
    assert win32.calls[-1] == ("flash", HWND)
    assert "AllowSetForegroundWindow(4242) に失敗" in caplog.text
    assert "前面化の依頼のイベントを開けません" in caplog.text
    assert "点滅させました" in caplog.text


def test_second_brings_window_itself(record, caplog):
    """1つ目が前面に出られなくても、2つ目に権限があれば2つ目から前面に出す"""
    si.write_record(record, PID, HWND)
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    with caplog.at_level(logging.INFO):
        assert run_activate(record, win32) is True
    assert "2つ目から" in caplog.text


def test_unexpected_error_is_logged(record, caplog):
    si.write_record(record, PID, HWND)
    win32 = FakeWin32({HWND: (PID, si.WINDOW_TITLE)})
    win32.window_pid = mock.MagicMock(side_effect=OSError("boom"))
    with caplog.at_level(logging.ERROR):
        assert run_activate(record, win32) is False
    assert "前面に出せません" in caplog.text
