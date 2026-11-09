"""src/api.py のテスト（JS から呼べる面の検証）。

win32com / pythoncom / webview のダイアログ / アイコン抽出はモックする。
ファイルは tmp_path 上に実際に作る。
"""
import importlib
import inspect
from unittest import mock

import pytest

from tests.helpers import make_file, make_url_file

UNC_EXE = "\\\\server\\share\\game.exe"

# JS から呼べてよい名前（script.js が使っているメソッドのみ）
EXPECTED_PUBLIC = {
    "add_category", "add_shortcut", "delete_category", "delete_shortcut",
    "edit_category", "edit_shortcut", "get_config", "get_themes",
    "launch_executable", "save_order", "select_file", "update_setting",
}


@pytest.fixture
def api_module(win32_mocks):
    return importlib.import_module("src.api")


@pytest.fixture
def icon(api_module, monkeypatch):
    """get_icon_base64 のモック（既定は取得失敗）"""
    m = mock.MagicMock(return_value="")
    monkeypatch.setattr(api_module, "get_icon_base64", m)
    return m


@pytest.fixture
def api(api_module, tmp_path, icon):
    return api_module.API(str(tmp_path / "settings.json"))


@pytest.fixture
def dialog(api_module, monkeypatch):
    """select_file のダイアログ。dialog.return_value に選択結果を入れる"""
    window = mock.MagicMock()
    monkeypatch.setattr(api_module.webview, "active_window", lambda: window)
    return window.create_file_dialog


@pytest.fixture
def cat_id(api):
    return api.get_config()["categories"][0]["id"]


def select(api, dialog, path):
    dialog.return_value = [path]
    assert api.select_file() == path


def shortcuts(api):
    return api.get_config()["categories"][0]["shortcuts"]


# --- JS から呼べる面 ----------------------------------------------------------

def test_only_expected_names_are_public(api):
    """pywebview は "_" 以外の属性を入れ子も含めて公開するため、公開名を固定する"""
    public = {n for n in dir(api) if not n.startswith("_")}
    assert public == EXPECTED_PUBLIC
    for name in public:
        assert inspect.ismethod(getattr(api, name)), name


def test_internal_objects_are_private(api):
    assert not hasattr(api, "config")
    assert not hasattr(api, "settings")
    assert not hasattr(api, "settings_path")


# --- add_shortcut: 正常系 -----------------------------------------------------

def test_add_exe(api, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "game.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "Game", path) == {"ok": True}
    s = shortcuts(api)[0]
    assert s["name"] == "Game"
    assert s["path"] == path
    assert "target" not in s


def test_add_lnk_saves_original_path_and_target(api, win32_mocks, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "Valorant.lnk")
    target = make_file(tmp_path, "Riot/RiotClientServices.exe")
    win32_mocks.shortcut.TargetPath = target
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "Valorant", path) == {"ok": True}
    s = shortcuts(api)[0]
    assert s["path"] == path
    assert s["target"] == target


def test_add_lnk_without_target_is_allowed(api, dialog, cat_id, tmp_path):
    """シェルフォルダ等（TargetPath が空）は従来どおり登録できる"""
    path = make_file(tmp_path, "Explorer.lnk")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "Explorer", path) == {"ok": True}
    assert "target" not in shortcuts(api)[0]


def test_add_url_saves_url_as_target(api, dialog, cat_id, tmp_path):
    path = make_url_file(tmp_path, "steam://rungameid/570")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "Dota", path) == {"ok": True}
    s = shortcuts(api)[0]
    assert s["path"] == path
    assert s["target"] == "steam://rungameid/570"


def test_add_bat_and_uppercase_ext(api, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "START.BAT")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "Start", path) == {"ok": True}


# --- add_shortcut: 拒否 -------------------------------------------------------

@pytest.mark.parametrize("name", ["setup.msi", "script.ps1", "doc.txt", "noext"])
def test_reject_extension(api, dialog, cat_id, tmp_path, name):
    path = make_file(tmp_path, name)
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "extension_not_allowed"}
    assert shortcuts(api) == []


@pytest.mark.parametrize("path", [UNC_EXE, "//server/share/game.exe", "\\\\?\\C:\\game.exe"])
def test_reject_unc_before_touching_filesystem(api, api_module, dialog, cat_id,
                                               monkeypatch, path):
    """UNC は存在チェック（SMB 接続）より前に拒否する"""
    isfile = mock.MagicMock(return_value=True)
    monkeypatch.setattr(api_module.os.path, "isfile", isfile)
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "unc_not_allowed"}
    isfile.assert_not_called()


def test_reject_missing_file(api, dialog, cat_id, tmp_path):
    path = str(tmp_path / "missing.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "file_not_found"}


@pytest.mark.parametrize("path", [None, "", 123, ["a.exe"]])
def test_reject_invalid_path(api, cat_id, path):
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "invalid_path"}


def test_reject_path_not_selected(api, cat_id, tmp_path):
    path = make_file(tmp_path, "game.exe")
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "path_not_selected"}


def test_reject_path_different_from_selected(api, dialog, cat_id, tmp_path):
    select(api, dialog, make_file(tmp_path, "a.exe"))
    other = make_file(tmp_path, "b.exe")
    assert api.add_shortcut(cat_id, "x", other) == {"ok": False, "error": "path_not_selected"}


def test_selected_path_matches_case_insensitively(api, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "Game.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path.upper()) == {"ok": True}


def test_only_last_selection_is_kept(api, dialog, cat_id, tmp_path):
    first = make_file(tmp_path, "a.exe")
    second = make_file(tmp_path, "b.exe")
    select(api, dialog, first)
    select(api, dialog, second)
    assert api.add_shortcut(cat_id, "a", first)["error"] == "path_not_selected"
    assert api.add_shortcut(cat_id, "b", second) == {"ok": True}


@pytest.mark.parametrize("cancel_result", [None, (), []])
def test_cancel_clears_selection(api, dialog, cat_id, tmp_path, cancel_result):
    path = make_file(tmp_path, "a.exe")
    select(api, dialog, path)
    dialog.return_value = cancel_result
    assert api.select_file() is None
    assert api.add_shortcut(cat_id, "a", path)["error"] == "path_not_selected"


def test_selection_is_consumed_after_add(api, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "a.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "a", path) == {"ok": True}
    assert api.add_shortcut(cat_id, "a", path)["error"] == "path_not_selected"
    assert len(shortcuts(api)) == 1


def test_reject_lnk_with_missing_target(api, win32_mocks, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "moved.lnk")
    win32_mocks.shortcut.TargetPath = str(tmp_path / "gone" / "game.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "target_not_found"}
    assert shortcuts(api) == []


def test_reject_lnk_with_unc_target(api, win32_mocks, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "net.lnk")
    win32_mocks.shortcut.TargetPath = UNC_EXE
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "unc_not_allowed"}


@pytest.mark.parametrize("url", ["file:///C:/Windows/System32/calc.exe",
                                 "ms-settings:privacy", "javascript:alert(1)"])
def test_reject_url_file_with_disallowed_url(api, dialog, cat_id, tmp_path, url):
    path = make_url_file(tmp_path, url)
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "url_not_allowed"}


def test_reject_broken_url_file(api, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "broken.url", "garbage")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": False, "error": "url_not_allowed"}


@pytest.mark.parametrize("name", ["", "   ", "\x00\x1f", None, 123])
def test_reject_invalid_name(api, dialog, cat_id, tmp_path, name):
    path = make_file(tmp_path, "a.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, name, path) == {"ok": False, "error": "invalid_name"}


@pytest.mark.parametrize("bad_cat", ["no-such-category", None, 1])
def test_reject_unknown_category(api, dialog, tmp_path, bad_cat):
    path = make_file(tmp_path, "a.exe")
    select(api, dialog, path)
    assert api.add_shortcut(bad_cat, "x", path) == {"ok": False, "error": "category_not_found"}


# --- アイコンの取得順 ---------------------------------------------------------

def test_lnk_icon_order(api, win32_mocks, icon, dialog, cat_id, tmp_path, monkeypatch):
    """IconLocation（インデックス付き）→ 解決先 exe → .lnk 自体 の順"""
    path = make_file(tmp_path, "game.lnk")
    target = make_file(tmp_path, "game.exe")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    win32_mocks.shortcut.TargetPath = target
    win32_mocks.shortcut.IconLocation = "%SystemRoot%\\System32\\shell32.dll,4"
    select(api, dialog, path)
    api.add_shortcut(cat_id, "x", path)
    assert icon.call_args_list == [
        mock.call("C:\\Windows\\System32\\shell32.dll", 4),
        mock.call(target, 0),
        mock.call(path, 0),
    ]


def test_lnk_icon_stops_at_first_success(api, win32_mocks, icon, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "game.lnk")
    win32_mocks.shortcut.TargetPath = make_file(tmp_path, "game.exe")
    win32_mocks.shortcut.IconLocation = "C:\\icons\\game.ico,0"
    icon.side_effect = lambda p, i: "data:image/webp;base64,AAAA" if p.endswith(".ico") else ""
    select(api, dialog, path)
    api.add_shortcut(cat_id, "x", path)
    assert icon.call_count == 1
    assert shortcuts(api)[0]["icon"] == "data:image/webp;base64,AAAA"


def test_lnk_without_icon_location_skips_it(api, icon, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "game.lnk")
    select(api, dialog, path)
    api.add_shortcut(cat_id, "x", path)
    assert icon.call_args_list == [mock.call(path, 0)]


def test_url_icon_order(api, icon, dialog, cat_id, tmp_path):
    """.url: IconFile → 元ファイル（解決先が URL でもそのまま候補に入れてよい）"""
    path = make_url_file(tmp_path, "steam://rungameid/570",
                         extra="IconFile=C:\\Steam\\game.ico\nIconIndex=0\n")
    select(api, dialog, path)
    api.add_shortcut(cat_id, "x", path)
    calls = icon.call_args_list
    assert calls[0] == mock.call("C:\\Steam\\game.ico", 0)
    assert calls[-1] == mock.call(path, 0)


def test_url_icon_unc_is_passed_to_guard(api, icon, dialog, cat_id, tmp_path):
    """UNC の IconFile は get_icon_base64 側のガードで拒否される（下の icons テスト）"""
    path = make_url_file(tmp_path, "steam://rungameid/570",
                         extra="IconFile=" + UNC_EXE + "\n")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": True}


# --- icons.get_icon_base64 の UNC ガード --------------------------------------

@pytest.mark.parametrize("path", [UNC_EXE, "//server/share/icon.ico"])
def test_icons_reject_unc_without_touching_filesystem(monkeypatch, path):
    from src.core import icons
    exists = mock.MagicMock(return_value=True)
    monkeypatch.setattr(icons.os.path, "exists", exists)
    assert icons.get_icon_base64(path) == ""
    exists.assert_not_called()


# --- update_setting -----------------------------------------------------------

@pytest.mark.parametrize("key, value", [
    ("theme", "valorant"),
    ("theme", "hydrangea_blue"),
    ("language", "ja"),
    ("language", "en"),
    ("card_size", "small"),
    ("card_size", "medium"),
])
def test_update_setting_allowed(api, key, value):
    assert api.update_setting(key, value) is True
    assert api.get_config()["config"][key] == value


@pytest.mark.parametrize("key, value", [
    ("theme", "../../evil"),
    ("theme", "nonexistent"),
    ("theme", None),
    ("language", "fr"),
    ("language", ["ja"]),
    ("card_size", "large"),
    ("unknown_key", "x"),
    ("categories", []),
    ("__proto__", "x"),
    (None, "ja"),
])
def test_update_setting_rejected(api, key, value):
    before = api.get_config()
    assert api.update_setting(key, value) is False
    assert api.get_config() == before


# --- 名前の正規化 -------------------------------------------------------------

def test_name_strips_control_and_bidi_chars(api, cat_id):
    assert api.edit_category(cat_id, " A\x00B\u202eC\u2066D\x7f\n ") is True
    assert api.get_config()["categories"][0]["name"] == "ABCD"


def test_name_is_truncated(api, cat_id):
    assert api.edit_category(cat_id, "あ" * 150) is True
    assert api.get_config()["categories"][0]["name"] == "あ" * 100


def test_name_keeps_emoji_and_quotes(api, cat_id):
    name = "Assassin's Creed 👨‍👩‍👧"
    assert api.edit_category(cat_id, name) is True
    assert api.get_config()["categories"][0]["name"] == name


@pytest.mark.parametrize("name", ["", "  ", "\x00", None, 1])
def test_add_category_rejects_invalid_name(api, name):
    before = api.get_config()
    assert api.add_category(name) is False
    assert api.get_config() == before


def test_edit_shortcut_validates_name(api, dialog, cat_id, tmp_path):
    path = make_file(tmp_path, "a.exe")
    select(api, dialog, path)
    api.add_shortcut(cat_id, "a", path)
    sid = shortcuts(api)[0]["id"]
    assert api.edit_shortcut(sid, "\x00") is False
    assert api.edit_shortcut(sid, "New\x07Name") is True
    assert shortcuts(api)[0]["name"] == "NewName"


@pytest.mark.parametrize("method", ["delete_category", "delete_shortcut", "launch_executable"])
def test_non_string_ids_are_rejected(api, method):
    assert getattr(api, method)({"id": "x"}) is False
