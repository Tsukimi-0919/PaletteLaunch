"""src/core/drop_guard.py のテスト（Phase 6）。

pywebview 6.1 では、JS から pywebviewFullPath を偽装して Python の drop ハンドラーに
届けられる（方法 A: _jsApiCallback('pywebviewEventHandler', {event: {...}, nodeId: 'document'})）。
ここでは pywebview の実際の処理（webview.util.js_bridge_call）に偽のイベントを通し、
DropGuard と API._handle_drop が弾くことを確認する。
"""
import importlib
import re
import threading
from pathlib import Path
from unittest import mock

import pytest

import webview.dom
import webview.util

from src.core import drop_guard as dg

ROOT = Path(__file__).resolve().parent.parent


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def real_dnd_state():
    """本物の webview.dom._dnd_state を使い、テスト後に元に戻す"""
    state = webview.dom._dnd_state
    saved_paths, saved_listeners = state["paths"], state["num_listeners"]
    state["paths"] = []
    yield state
    state["paths"], state["num_listeners"] = saved_paths, saved_listeners


def fake_state():
    return {"num_listeners": 0, "paths": []}


# --- バージョン固定 -----------------------------------------------------------

def test_pywebview_is_pinned_to_checked_version():
    """requirements.txt の固定と、仕組みを確認したバージョンが一致していること"""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pins = re.findall(r"^pywebview==(\S+)\s*$", text, flags=re.M)
    assert pins == [dg.EXPECTED_PYWEBVIEW_VERSION]


# --- install: 安全側に倒れること ---------------------------------------------

def test_install_replaces_paths():
    guard, state = dg.DropGuard(), fake_state()
    state["paths"].append(("old.exe", "C:\\old.exe"))
    assert guard.install(dnd_state=state, version="6.1") is True
    assert guard.enabled
    assert isinstance(state["paths"], dg._RecordingPaths)
    assert list(state["paths"]) == [("old.exe", "C:\\old.exe")]  # 中身は引き継ぐ


@pytest.mark.parametrize("version", ["6.0", "6.1.1", "6.2", "7.0", ""])
def test_install_refuses_other_versions(version):
    guard, state = dg.DropGuard(), fake_state()
    original = state["paths"]
    assert guard.install(dnd_state=state, version=version) is False
    assert not guard.enabled
    assert state["paths"] is original


@pytest.mark.parametrize("installed", [None, "6.2"])
def test_install_refuses_when_installed_version_differs(monkeypatch, installed):
    monkeypatch.setattr(dg, "_installed_pywebview_version", lambda: installed)
    guard, state = dg.DropGuard(), fake_state()
    assert guard.install(dnd_state=state) is False
    assert not guard.enabled
    assert not isinstance(state["paths"], dg._RecordingPaths)


@pytest.mark.parametrize("state", [
    "not-a-dict",
    {"paths": []},  # num_listeners が無い
    {"num_listeners": 0, "paths": ()},  # paths が list ではない
    {"num_listeners": 0},
])
def test_install_refuses_unexpected_structure(state):
    guard = dg.DropGuard()
    assert guard.install(dnd_state=state, version="6.1") is False
    assert not guard.enabled


def test_install_refuses_when_assignment_does_not_stick():
    class Sticky(dict):
        def __setitem__(self, key, value):
            pass  # 差し替えが効かない

    guard = dg.DropGuard()
    state = Sticky(num_listeners=0, paths=[])
    assert guard.install(dnd_state=state, version="6.1") is False
    assert not guard.enabled


def test_install_refuses_on_exception():
    class Broken(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("boom")

    guard = dg.DropGuard()
    assert guard.install(dnd_state=Broken(num_listeners=0, paths=[]), version="6.1") is False
    assert not guard.enabled


def test_install_refuses_when_util_uses_another_state(real_dnd_state, monkeypatch):
    monkeypatch.setattr(webview.util, "_dnd_state", fake_state())
    guard = dg.DropGuard()
    assert guard.install(version="6.1") is False
    assert not guard.enabled
    assert not isinstance(real_dnd_state["paths"], dg._RecordingPaths)


def test_install_on_real_pywebview(real_dnd_state):
    guard = dg.DropGuard()
    assert guard.install() is True  # インストール済みの pywebview は 6.1
    assert webview.dom._dnd_state["paths"] is webview.util._dnd_state["paths"]
    assert isinstance(webview.util._dnd_state["paths"], dg._RecordingPaths)


def test_disabled_guard_accepts_nothing():
    guard = dg.DropGuard()  # install していない
    guard._record_native([("a.exe", "C:\\a.exe")])
    assert guard.consume(["C:\\a.exe"]) == []


# --- 記録と照合 ---------------------------------------------------------------

@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def guard(clock):
    g = dg.DropGuard(clock=clock)
    state = fake_state()
    assert g.install(dnd_state=state, version="6.1")
    g.state = state
    return g


def native_drop(guard, *paths):
    """edgechromium.py の on_script_notify と同じ操作"""
    guard.state["paths"] += [(p.rsplit("\\", 1)[-1], p) for p in paths]


def test_consume_accepts_only_native_paths(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    assert guard.consume(["C:\\Games\\a.exe", "C:\\Windows\\System32\\calc.exe"]) == \
        ["C:\\Games\\a.exe"]


def test_consume_is_case_insensitive(guard):
    native_drop(guard, "C:\\Games\\A.exe")
    assert guard.consume(["c:\\games\\a.EXE"]) == ["C:\\Games\\A.exe"]


def test_consume_clears_record(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    assert guard.consume(["C:\\Games\\a.exe"]) == ["C:\\Games\\a.exe"]
    assert guard.consume(["C:\\Games\\a.exe"]) == []


def test_only_last_drop_is_kept(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    native_drop(guard, "C:\\Games\\b.exe")
    assert guard.consume(["C:\\Games\\a.exe", "C:\\Games\\b.exe"]) == ["C:\\Games\\b.exe"]


def test_record_expires(guard, clock):
    native_drop(guard, "C:\\Games\\a.exe")
    clock.now += dg.DROP_TTL_SECONDS + 1
    assert guard.consume(["C:\\Games\\a.exe"]) == []


@pytest.mark.parametrize("claimed", [[None], [123], [""], ["C:\\a\0.exe"], [{"x": 1}]])
def test_consume_ignores_bad_values(guard, claimed):
    native_drop(guard, "C:\\Games\\a.exe")
    assert guard.consume(claimed) == []


def test_recording_list_still_behaves_like_list(guard):
    """pywebview の util.py は記録からの remove を行う"""
    native_drop(guard, "C:\\Games\\a.exe")
    item = guard.state["paths"][0]
    guard.state["paths"].remove(item)
    assert list(guard.state["paths"]) == []


# --- 回帰テスト: 偽装方法 A ---------------------------------------------------

def forged_event(path, name="calc.exe"):
    """JS が _jsApiCallback('pywebviewEventHandler', ...) に渡す普通のオブジェクト"""
    return {
        "event": {"type": "drop", "dataTransfer": {"files": [
            {"name": name, "pywebviewFullPath": path}]}},
        "nodeId": "document",
    }


@pytest.fixture
def bridge(real_dnd_state, win32_mocks, tmp_path):
    """本物の js_bridge_call（pywebview 6.1）→ document の drop ハンドラー → API._handle_drop"""
    api_module = importlib.import_module("src.api")
    guard = dg.DropGuard()
    assert guard.install()
    api = api_module.API(str(tmp_path / "settings.json"), drop_guard=guard)
    js_window = mock.MagicMock()
    api._attach_window(js_window)

    done = threading.Event()

    def handler(event):
        try:
            api._handle_drop(event)
        finally:
            done.set()

    element = mock.MagicMock()
    element._event_handlers = {"drop": [handler]}
    window = mock.MagicMock()
    window.dom._elements = {"document": element}

    def send(params):
        done.clear()
        webview.util.js_bridge_call(window, "pywebviewEventHandler", params, "eventHandler")
        assert done.wait(5)

    return mock.NonCallableMock(api=api, send=send, js_window=js_window,
                                state=real_dnd_state, cat_id=api.get_config()["categories"][0]["id"])


def test_forged_full_path_is_rejected(bridge, tmp_path):
    target = tmp_path / "evil.exe"
    target.write_text("")
    bridge.send(forged_event(str(target), "evil.exe"))

    bridge.js_window.run_js.assert_not_called()
    result = bridge.api.add_shortcut(bridge.cat_id, "evil", str(target))
    assert result == {"ok": False, "error": "path_not_selected"}


def test_forged_path_with_same_name_as_real_drop_is_rejected(bridge, tmp_path):
    """本物のドロップと同じファイル名でも、pywebview がパスを上書きするため偽のパスは残らない。
    上書きされなかった場合も、記録に無いパスは DropGuard が弾く"""
    real = tmp_path / "real" / "game.exe"
    real.parent.mkdir()
    real.write_text("")
    evil = tmp_path / "evil" / "game.exe"
    evil.parent.mkdir()
    evil.write_text("")

    bridge.state["paths"] += [("game.exe", str(real))]
    params = forged_event(str(evil), "game.exe")
    params["event"]["dataTransfer"]["files"].append(
        {"name": "other.exe", "pywebviewFullPath": str(evil)})
    bridge.send(params)

    assert bridge.api.add_shortcut(bridge.cat_id, "evil", str(evil)) == \
        {"ok": False, "error": "path_not_selected"}
    assert bridge.api.add_shortcut(bridge.cat_id, "game", str(real)) == {"ok": True}


def test_native_drop_is_accepted(bridge, tmp_path):
    real = tmp_path / "game.exe"
    real.write_text("")
    bridge.state["paths"] += [("game.exe", str(real))]  # WebView2 の FilesDropped
    bridge.send(forged_event("ignored", "game.exe"))  # pywebview が本物のパスで上書きする

    bridge.js_window.run_js.assert_called_once()
    assert str(real).replace("\\", "\\\\") in bridge.js_window.run_js.call_args.args[0]
    assert bridge.api.add_shortcut(bridge.cat_id, "game", str(real)) == {"ok": True}
