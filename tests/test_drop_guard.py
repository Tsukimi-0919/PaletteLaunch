"""src/core/drop_guard.py のテスト（Phase 6）。

pywebview 6.1 では、JS から pywebviewFullPath を偽装して Python の drop ハンドラーに
届けられる（方法 A: _jsApiCallback('pywebviewEventHandler', {event: {...}, nodeId: 'document'})）。
ここでは pywebview の実際の処理（webview.util.js_bridge_call）に偽のイベントを通し、
DropGuard と API._handle_drop が弾くことを確認する。
"""
import importlib
import json
import re
import threading
import time
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


def files(*items):
    """drop イベントの files（(name, pywebviewFullPath) の組。パスは省略可）"""
    out = []
    for item in items:
        name, path = item if isinstance(item, tuple) else (item.rsplit("\\", 1)[-1], item)
        f = {"name": name}
        if path is not None:
            f["pywebviewFullPath"] = path
        out.append(f)
    return out


def test_disabled_guard_accepts_nothing():
    guard = dg.DropGuard(wait=0)  # install していない
    guard._record_native([("a.exe", "C:\\a.exe")])
    check = guard.consume(files("C:\\a.exe"))
    assert check.accepted == []
    assert check.reason == dg.REASON_DISABLED


# --- 記録と照合 ---------------------------------------------------------------

@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def guard(clock):
    g = dg.DropGuard(clock=clock, wait=0.05)
    state = fake_state()
    assert g.install(dnd_state=state, version="6.1")
    g.state = state
    return g


def native_drop(guard, *paths):
    """edgechromium.py の on_script_notify と同じ操作"""
    guard.state["paths"] += [(p.rsplit("\\", 1)[-1], p) for p in paths]


def test_consume_accepts_only_native_paths(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    check = guard.consume(files("C:\\Games\\a.exe", "C:\\Windows\\System32\\calc.exe"))
    assert check.accepted == ["C:\\Games\\a.exe"]
    assert check.rejected == [("calc.exe", dg.REASON_NOT_RECORDED)]


def test_consume_is_case_insensitive(guard):
    native_drop(guard, "C:\\Games\\A.exe")
    assert guard.consume(files(("x", "c:\\games\\a.EXE"))).accepted == ["C:\\Games\\A.exe"]


def test_accepted_path_is_always_the_native_one(guard):
    """pywebviewFullPath が無い（到着順が逆）ときはファイル名で照合し、パスは記録の値を使う"""
    native_drop(guard, "C:\\Games\\a.exe")
    assert guard.consume(files(("a.exe", None))).accepted == ["C:\\Games\\a.exe"]


def test_forged_path_with_recorded_name_gets_native_path(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    check = guard.consume(files(("a.exe", "C:\\Windows\\System32\\calc.exe")))
    assert check.accepted == ["C:\\Games\\a.exe"]


def test_consume_clears_record(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    assert guard.consume(files("C:\\Games\\a.exe")).accepted == ["C:\\Games\\a.exe"]
    check = guard.consume(files("C:\\Games\\a.exe"))
    assert check.accepted == [] and check.reason == dg.REASON_NO_RECORD


def test_consume_removes_used_entries_from_pywebview_list(guard):
    native_drop(guard, "C:\\Games\\a.exe", "C:\\Games\\b.exe")
    guard.consume(files(("a.exe", None)))
    assert list(guard.state["paths"]) == [("b.exe", "C:\\Games\\b.exe")]


def test_only_last_drop_is_kept(guard):
    native_drop(guard, "C:\\Games\\a.exe")
    native_drop(guard, "C:\\Games\\b.exe")
    check = guard.consume(files("C:\\Games\\a.exe", "C:\\Games\\b.exe"))
    assert check.accepted == ["C:\\Games\\b.exe"]


def test_record_expires(guard, clock):
    native_drop(guard, "C:\\Games\\a.exe")
    clock.now += dg.DROP_TTL_SECONDS + 1
    check = guard.consume(files("C:\\Games\\a.exe"))
    assert check.accepted == [] and check.reason == dg.REASON_EXPIRED


def test_no_record_is_rejected_after_waiting(guard):
    """記録が無いまま受け付ける方向には倒れない"""
    start = time.monotonic()
    check = guard.consume(files("C:\\Games\\a.exe"))
    assert check.accepted == [] and check.reason == dg.REASON_NO_RECORD
    assert time.monotonic() - start >= 0.04


def test_waits_for_late_native_record(clock):
    """DOM の drop イベントが FilesDropped より先に届いても、記録を待って照合する"""
    guard = dg.DropGuard(clock=clock, wait=2.0)
    state = fake_state()
    assert guard.install(dnd_state=state, version="6.1")
    timer = threading.Timer(0.1, lambda: state["paths"].__iadd__([("a.exe", "C:\\Games\\a.exe")]))
    timer.start()
    try:
        check = guard.consume(files(("a.exe", None)))
    finally:
        timer.join()
    assert check.accepted == ["C:\\Games\\a.exe"]


@pytest.mark.parametrize("claimed", [None, 123, "", "C:\\a\0.exe"])
def test_consume_ignores_bad_values(guard, claimed):
    native_drop(guard, "C:\\Games\\a.exe")
    assert guard.consume([{"name": "zzz", "pywebviewFullPath": claimed}]).accepted == []


@pytest.mark.parametrize("value", [None, [], [None], ["x"], [123]])
def test_consume_without_files(guard, value):
    check = guard.consume(value)
    assert check.accepted == [] and check.reason == dg.REASON_NO_FILES


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


def js_payload(js_window):
    js = js_window.run_js.call_args.args[0]
    start = js.index("paletteLaunchOnDrop(", js.index("&&")) + len("paletteLaunchOnDrop(")
    return json.loads(js[start:js.rindex(")")])


@pytest.fixture
def bridge(real_dnd_state, win32_mocks, tmp_path):
    """本物の js_bridge_call（pywebview 6.1）→ document の drop ハンドラー → API._handle_drop"""
    api_module = importlib.import_module("src.api")
    guard = dg.DropGuard(wait=0.2)
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

    def send(params, before_wait=None):
        done.clear()
        webview.util.js_bridge_call(window, "pywebviewEventHandler", params, "eventHandler")
        if before_wait:
            before_wait()
        assert done.wait(5)

    return mock.NonCallableMock(api=api, send=send, js_window=js_window,
                                state=real_dnd_state, cat_id=api.get_config()["categories"][0]["id"])


def test_forged_full_path_is_rejected(bridge, tmp_path):
    target = tmp_path / "evil.exe"
    target.write_text("")
    bridge.send(forged_event(str(target), "evil.exe"))

    # UI には理由だけが届き、パスは届かない
    assert js_payload(bridge.js_window) == {"files": [], "error": dg.REASON_NO_RECORD}
    result = bridge.api.add_shortcut(bridge.cat_id, "evil", str(target))
    assert result == {"ok": False, "error": "path_not_selected"}
    assert bridge.api.add_dropped_shortcuts(bridge.cat_id, [str(target)])["results"] == \
        [{"path": str(target), "ok": False, "error": "path_not_selected"}]


def test_forged_path_with_same_name_as_real_drop_is_rejected(bridge, tmp_path):
    """本物のドロップと同じファイル名でも、受け付けるのは記録（ネイティブ側）のパスだけ"""
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

    assert js_payload(bridge.js_window)["files"] == [{"name": "game", "path": str(real)}]
    assert bridge.api.add_shortcut(bridge.cat_id, "evil", str(evil)) == \
        {"ok": False, "error": "path_not_selected"}
    assert bridge.api.add_shortcut(bridge.cat_id, "game", str(real)) == {"ok": True}


def test_native_drop_is_accepted(bridge, tmp_path):
    real = tmp_path / "game.exe"
    real.write_text("")
    bridge.state["paths"] += [("game.exe", str(real))]  # WebView2 の FilesDropped
    bridge.send(forged_event("ignored", "game.exe"))  # pywebview が本物のパスで上書きする

    assert js_payload(bridge.js_window) == {
        "files": [{"name": "game", "path": str(real)}], "error": None}
    assert bridge.api.add_dropped_shortcuts(bridge.cat_id, [str(real)]) == {
        "results": [{"path": str(real), "ok": True}], "error": None}


def test_native_record_after_dom_event_is_accepted(bridge, tmp_path):
    """実機で起きた順番: DOM の drop イベントが先、FilesDropped が後"""
    real = tmp_path / "game.exe"
    real.write_text("")
    event = {"event": {"type": "drop", "dataTransfer": {"files": [{"name": "game.exe"}]}},
             "nodeId": "document"}

    def late_native():
        time.sleep(0.05)
        bridge.state["paths"] += [("game.exe", str(real))]

    bridge.send(event, before_wait=late_native)
    assert js_payload(bridge.js_window)["files"] == [{"name": "game", "path": str(real)}]
    assert bridge.api.add_dropped_shortcuts(bridge.cat_id, [str(real)])["results"][0]["ok"]
