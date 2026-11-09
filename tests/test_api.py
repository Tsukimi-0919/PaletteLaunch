"""src/api.py のテスト（JS から呼べる面の検証）。

win32com / pythoncom / webview のダイアログ / アイコン抽出はモックする。
ファイルは tmp_path 上に実際に作る。
"""
import base64
import importlib
import inspect
import json
import logging
from io import BytesIO
from unittest import mock

import pytest
from PIL import Image

from tests.helpers import make_file, make_url_file

UNC_EXE = "\\\\server\\share\\game.exe"

# JS から呼べてよい名前（script.js が使っているメソッドのみ）
EXPECTED_PUBLIC = {
    "add_category", "add_dropped_shortcuts", "add_shortcut", "delete_category", "delete_shortcut",
    "edit_category", "edit_shortcut", "get_config", "get_load_status", "get_themes",
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


# --- Phase 5: 保存の失敗・読み取り専用モード ----------------------------------

def _seed(api, dialog, tmp_path):
    """カテゴリー 2 つ・ショートカット 3 つの状態を作る"""
    assert api.add_category("Second") is True
    cats = api.get_config()["categories"]
    first, second = cats[0]["id"], cats[1]["id"]
    for cat, name in ((first, "a"), (first, "b"), (second, "c")):
        path = make_file(tmp_path, f"apps/{name}.exe")
        select(api, dialog, path)
        assert api.add_shortcut(cat, name, path) == {"ok": True}
    return api.get_config()


def _order(data):
    return [(c["name"], [s["name"] for s in c["shortcuts"]]) for c in data["categories"]]


def _ids(data):
    cats = {c["name"]: c["id"] for c in data["categories"]}
    items = {s["name"]: s["id"] for c in data["categories"] for s in c["shortcuts"]}
    return cats, items


def test_get_load_status_normal(api):
    assert api.get_load_status() == {"read_only": False, "reason": None,
                                     "restored_from_backup": False, "corrupt_copy": None}


@pytest.fixture
def broken_api(api_module, tmp_path, icon):
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{"config": {"theme": "apex"}, "categories": [')
    return api_module.API(str(settings)), settings


def test_read_only_status_reports_only_file_name(broken_api):
    api, settings = broken_api
    status = api.get_load_status()
    assert status["read_only"] is True
    assert status["reason"] == "corrupt"
    assert status["corrupt_copy"].startswith("settings.corrupt-")
    assert "\\" not in status["corrupt_copy"] and "/" not in status["corrupt_copy"]
    assert (settings.parent / status["corrupt_copy"]).is_file()


def test_read_only_refuses_every_save(broken_api, dialog, tmp_path):
    api, settings = broken_api
    before = settings.read_bytes()
    cat_id = api.get_config()["categories"][0]["id"]
    path = make_file(tmp_path, "game.exe")
    select(api, dialog, path)

    assert api.add_shortcut(cat_id, "game", path) == {"ok": False, "error": "read_only"}
    assert api.add_category("New") is False
    assert api.edit_category(cat_id, "Renamed") is False
    assert api.delete_category(cat_id) is False
    assert api.delete_shortcut("x") is False
    assert api.update_setting("theme", "valorant") is False
    assert api.update_setting("language", "en") is False
    assert api.save_order([{"id": cat_id, "shortcuts": []}]) is False

    assert settings.read_bytes() == before
    assert not (tmp_path / "settings.json.bak").exists()


def test_save_failure_is_reported_and_keeps_file(api, api_module, dialog, cat_id, tmp_path,
                                                 monkeypatch):
    settings = tmp_path / "settings.json"
    before = settings.read_bytes()

    from src.core import config as config_module
    real_write = config_module.atomic_write
    disk_full = {"on": True}

    def write(path, writer):
        if disk_full["on"]:
            raise OSError(28, "No space left on device")
        real_write(path, writer)

    monkeypatch.setattr(config_module, "atomic_write", write)
    path = make_file(tmp_path, "game.exe")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "game", path) == {"ok": False, "error": "save_failed"}
    assert api.add_category("New") is False
    assert api.update_setting("theme", "valorant") is False
    assert settings.read_bytes() == before
    assert api.get_load_status()["read_only"] is False
    # 保存に失敗した選択は残る（空きができてからもう一度押せば登録できる）
    disk_full["on"] = False
    assert api.add_shortcut(cat_id, "game", path) == {"ok": True}


def test_save_order_reorders(api, dialog, tmp_path):
    data = _seed(api, dialog, tmp_path)
    cats, items = _ids(data)
    order = [{"id": cats["Second"], "shortcuts": [items["a"], items["c"]]},
             {"id": cats["General"], "shortcuts": [items["b"]]}]
    assert api.save_order(order) is True
    assert _order(api.get_config()) == [("Second", ["a", "c"]), ("General", ["b"])]


def test_save_order_keeps_missing_items_at_end(api, dialog, tmp_path):
    """並び順に載っていないカテゴリー・ショートカットは消さずに末尾へ残す"""
    data = _seed(api, dialog, tmp_path)
    cats, items = _ids(data)
    assert api.save_order([{"id": cats["Second"], "shortcuts": [items["b"]]}]) is True
    # b は Second へ移動。a は元の General の末尾、c は元の Second の末尾に残る
    assert _order(api.get_config()) == [("Second", ["b", "c"]), ("General", ["a"])]


def test_save_order_with_empty_list_changes_nothing(api, dialog, tmp_path):
    data = _seed(api, dialog, tmp_path)
    assert api.save_order([]) is True
    assert _order(api.get_config()) == _order(data)


def test_save_order_ignores_duplicate_and_unknown_ids(api, dialog, tmp_path):
    data = _seed(api, dialog, tmp_path)
    cats, items = _ids(data)
    order = [{"id": cats["General"], "shortcuts": [items["c"], "unknown", items["c"], items["a"]]},
             {"id": "unknown-category", "shortcuts": [items["b"]]},
             {"id": cats["General"], "shortcuts": [items["b"]]},
             {"id": cats["Second"], "shortcuts": [items["a"]]}]
    assert api.save_order(order) is True
    # 2 回目の General は無視、知らないカテゴリーの中の b も無視（元の General の末尾に残る）
    assert _order(api.get_config()) == [("General", ["c", "a", "b"]), ("Second", [])]


@pytest.mark.parametrize("bad", [
    None, "x", {"id": "x"}, [None], [{"id": 1, "shortcuts": []}],
    [{"id": "x"}], [{"id": "x", "shortcuts": "abc"}], [{"id": "x", "shortcuts": [1]}],
])
def test_save_order_rejects_malformed_input(api, dialog, tmp_path, bad):
    _seed(api, dialog, tmp_path)
    settings = tmp_path / "settings.json"
    before = settings.read_bytes()
    assert api.save_order(bad) is False
    assert settings.read_bytes() == before


def test_api_passes_example_path(api_module, tmp_path):
    example = tmp_path / "example.json"
    example.write_text('{"config": {}, "categories": [{"id": "e", "name": "Example", "shortcuts": []}]}',
                       encoding="utf-8")
    api = api_module.API(str(tmp_path / "settings.json"), str(example))
    assert api.get_config()["categories"][0]["name"] == "Example"


# --- Phase 6: .url の IconIndex ------------------------------------------------

def test_url_icon_index_is_used(api, icon, dialog, cat_id, tmp_path):
    path = make_url_file(tmp_path, "steam://rungameid/570",
                         extra="IconFile=C:\\Games\\game.exe\nIconIndex=3\n")
    select(api, dialog, path)
    api.add_shortcut(cat_id, "x", path)
    assert icon.call_args_list[0] == mock.call("C:\\Games\\game.exe", 3)


def test_url_icon_index_invalid_falls_back_to_zero(api, icon, dialog, cat_id, tmp_path):
    path = make_url_file(tmp_path, "steam://rungameid/570",
                         extra="IconFile=C:\\Games\\game.exe\nIconIndex=abc\n")
    select(api, dialog, path)
    api.add_shortcut(cat_id, "x", path)
    assert icon.call_args_list[0] == mock.call("C:\\Games\\game.exe", 0)


def test_blank_icon_falls_back_to_next_candidate(api, icon, dialog, cat_id, tmp_path):
    """get_icon_base64 が透明を "" で返したら次の候補へ進み、最後まで空ならプレースホルダー"""
    path = make_url_file(tmp_path, "steam://rungameid/1009850",
                         extra="IconFile=C:\\Steam\\blank.ico\nIconIndex=0\n")
    select(api, dialog, path)
    assert api.add_shortcut(cat_id, "x", path) == {"ok": True}
    assert len(icon.call_args_list) >= 2
    assert shortcuts(api)[0]["icon"] == ""


# --- Phase 6: 保存済みの透明なアイコン --------------------------------------------

def _webp_uri(alpha):
    out = BytesIO()
    Image.new("RGBA", (48, 48), (255, 0, 0, alpha)).save(out, format="WEBP")
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()


def test_get_config_hides_blank_icons_without_rewriting(api_module, tmp_path, icon):
    blank, visible = _webp_uri(0), _webp_uri(255)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"config": {}, "categories": [{
        "id": "c1", "name": "Games", "shortcuts": [
            {"id": "s1", "name": "OVR", "path": "C:\\a.url", "icon": blank},
            {"id": "s2", "name": "Game", "path": "C:\\b.exe", "icon": visible},
        ]}]}), encoding="utf-8")
    before = settings.read_bytes()
    api = api_module.API(str(settings))

    items = api.get_config()["categories"][0]["shortcuts"]
    assert items[0]["icon"] == ""
    assert items[1]["icon"] == visible
    assert settings.read_bytes() == before
    # 他の保存操作でも、保存済みのアイコンは書き換えない（表示用の変換だけ）
    assert api.edit_category("c1", "Renamed") is True
    saved = json.loads(settings.read_text(encoding="utf-8"))
    assert saved["categories"][0]["shortcuts"][0]["icon"] == blank


def test_logs_do_not_contain_icon_data(api, icon, dialog, cat_id, tmp_path, caplog):
    secret = "data:image/webp;base64," + "QUJD" * 50
    icon.return_value = secret
    path = make_file(tmp_path, "game.exe")
    with caplog.at_level(logging.DEBUG):
        select(api, dialog, path)
        api.add_shortcut(cat_id, "x", path)
        api.get_config()
        api.update_setting("theme", secret)
        api.update_setting(secret, "x")
        api.save_order([{"id": secret, "shortcuts": [1]}])
        api.add_shortcut(cat_id, "x", secret + ".exe")
    assert "QUJDQUJD" not in caplog.text


# --- Phase 6: ドロップで受け取ったパス ------------------------------------------

class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _fake_consume(trusted):
    """DropGuard.consume の代わり: pywebviewFullPath が trusted にあるものだけ受け付ける"""
    from src.core.drop_guard import DropCheck, REASON_NO_FILES, REASON_NOT_RECORDED

    def consume(files):
        check = DropCheck()
        if not files:
            check.reason = REASON_NO_FILES
            return check
        for f in files:
            path = f.get("pywebviewFullPath")
            if path in trusted:
                check.accepted.append(path)
            else:
                check.rejected.append((f.get("name"), REASON_NOT_RECORDED))
        if not check.accepted:
            check.reason = REASON_NOT_RECORDED
        return check
    return consume


@pytest.fixture
def drop(api_module, tmp_path, icon):
    """有効な DropGuard（モック）を持つ API"""
    clock = FakeClock()
    guard = mock.MagicMock(enabled=True)
    guard.trusted = set()
    guard.consume.side_effect = _fake_consume(guard.trusted)
    api = api_module.API(str(tmp_path / "settings.json"), drop_guard=guard, clock=clock)
    window = mock.MagicMock()
    api._attach_window(window)
    return mock.NonCallableMock(api=api, guard=guard, window=window, clock=clock,
                                cat_id=api.get_config()["categories"][0]["id"])


def drop_event(*paths):
    return {"type": "drop", "dataTransfer": {"files": [
        {"name": p.rsplit("\\", 1)[-1], "pywebviewFullPath": p} for p in paths]}}


def drop_payload(window):
    js = window.run_js.call_args.args[0]
    assert js.startswith("window.paletteLaunchOnDrop && window.paletteLaunchOnDrop(")
    start = js.index("paletteLaunchOnDrop(", js.index("&&")) + len("paletteLaunchOnDrop(")
    return json.loads(js[start:js.rindex(")")])


def test_dropped_path_can_be_added(drop, tmp_path):
    path = make_file(tmp_path, "My Game.exe")
    drop.guard.trusted.add(path)
    drop.api._handle_drop(drop_event(path))

    assert drop_payload(drop.window) == {"files": [{"name": "My Game", "path": path}],
                                         "error": None}
    assert drop.api.add_dropped_shortcuts(drop.cat_id, [path]) == \
        {"results": [{"path": path, "ok": True}], "error": None}
    assert shortcuts(drop.api)[0]["name"] == "My Game"
    # 使ったら消える
    assert drop.api.add_shortcut(drop.cat_id, "My Game", path) == \
        {"ok": False, "error": "path_not_selected"}


def test_drop_payload_is_json_escaped(drop, tmp_path):
    path = make_file(tmp_path, "x'y\u2028z.exe")
    drop.guard.trusted.add(path)
    drop.api._handle_drop(drop_event(path))
    js = drop.window.run_js.call_args.args[0]
    assert "\u2028" not in js  # ensure_ascii \u3067 \u2028 \u306b\u30a8\u30b9\u30b1\u30fc\u30d7\u3055\u308c\u308b
    assert drop_payload(drop.window)["files"] == [{"name": "x'y\u2028z", "path": path}]


def test_dropped_path_still_validated(drop, tmp_path):
    """ドロップでも Phase 2 の検証（拡張子など）は通す"""
    path = make_file(tmp_path, "notes.txt")
    drop.guard.trusted.add(path)
    drop.api._handle_drop(drop_event(path))
    assert drop.api.add_dropped_shortcuts(drop.cat_id, [path])["results"] == \
        [{"path": path, "ok": False, "error": "extension_not_allowed"}]


def test_untrusted_drop_reports_reason(drop, tmp_path):
    """拒否したときも、理由を UI に知らせる（パスは知らせない）"""
    path = make_file(tmp_path, "evil.exe")
    drop.api._handle_drop(drop_event(path))
    assert drop_payload(drop.window) == {"files": [], "error": "drop_not_recorded"}
    assert drop.api.add_shortcut(drop.cat_id, "evil", path) == \
        {"ok": False, "error": "path_not_selected"}


def test_only_last_drop_is_accepted(drop, tmp_path):
    first = make_file(tmp_path, "a.exe")
    second = make_file(tmp_path, "b.exe")
    drop.guard.trusted.update({first, second})
    drop.api._handle_drop(drop_event(first))
    drop.api._handle_drop(drop_event(second))
    assert drop.api.add_shortcut(drop.cat_id, "a", first) == \
        {"ok": False, "error": "path_not_selected"}
    assert drop.api.add_shortcut(drop.cat_id, "b", second) == {"ok": True}


def test_untrusted_drop_clears_previous_drop(drop, tmp_path):
    real = make_file(tmp_path, "a.exe")
    drop.guard.trusted.add(real)
    drop.api._handle_drop(drop_event(real))
    drop.api._handle_drop(drop_event(make_file(tmp_path, "evil.exe")))
    assert drop.api.add_shortcut(drop.cat_id, "a", real) == \
        {"ok": False, "error": "path_not_selected"}


def test_dropped_path_expires(drop, tmp_path, api_module):
    path = make_file(tmp_path, "a.exe")
    drop.guard.trusted.add(path)
    drop.api._handle_drop(drop_event(path))
    drop.clock.now += api_module.DROPPED_PATH_TTL_SECONDS + 1
    assert drop.api.add_shortcut(drop.cat_id, "a", path) == \
        {"ok": False, "error": "path_not_selected"}


def test_multiple_dropped_files(drop, tmp_path):
    a, b = make_file(tmp_path, "a.exe"), make_file(tmp_path, "b.bat")
    drop.guard.trusted.update({a, b})
    drop.api._handle_drop(drop_event(a, b))
    result = drop.api.add_dropped_shortcuts(drop.cat_id, [a, b])
    assert [r["ok"] for r in result["results"]] == [True, True]


def test_drop_without_target_category(drop, tmp_path):
    """カテゴリーの外にドロップしたら追加せず、理由を返し、ドロップの記録も消す"""
    path = make_file(tmp_path, "a.exe")
    drop.guard.trusted.add(path)
    drop.api._handle_drop(drop_event(path))
    assert drop.api.add_dropped_shortcuts(None, [path]) == \
        {"results": [], "error": "drop_target_missing"}
    assert shortcuts(drop.api) == []
    assert drop.api.add_shortcut(drop.cat_id, "a", path) == \
        {"ok": False, "error": "path_not_selected"}


@pytest.mark.parametrize("paths", [None, "C:\\a.exe", [1], [None]])
def test_add_dropped_rejects_bad_paths(drop, paths):
    assert drop.api.add_dropped_shortcuts(drop.cat_id, paths) == \
        {"results": [], "error": "invalid_path"}


@pytest.mark.parametrize("enabled_guard", [None, False])
def test_drop_ignored_without_enabled_guard(api_module, tmp_path, icon, enabled_guard):
    """検証が無効なら、ドロップを受け付けない（検証なしで受け付ける方向に倒れない）"""
    guard = None if enabled_guard is None else mock.MagicMock(enabled=False)
    api = api_module.API(str(tmp_path / "settings.json"), drop_guard=guard)
    window = mock.MagicMock()
    api._attach_window(window)
    path = make_file(tmp_path, "a.exe")
    api._handle_drop(drop_event(path))
    assert drop_payload(window) == {"files": [], "error": "drop_disabled"}
    if guard is not None:
        guard.consume.assert_not_called()
    cat_id = api.get_config()["categories"][0]["id"]
    assert api.add_shortcut(cat_id, "a", path) == {"ok": False, "error": "path_not_selected"}


@pytest.mark.parametrize("event", [None, {}, {"dataTransfer": None},
                                   {"dataTransfer": {"files": "x"}}, {"dataTransfer": {}},
                                   {"dataTransfer": {"files": []}}])
def test_non_file_drop_is_ignored(drop, event):
    """ファイルを含まない drop（カードの並べ替えなど）は UI に何も知らせない"""
    drop.api._handle_drop(event)
    drop.window.run_js.assert_not_called()
    drop.guard.consume.assert_not_called()


def test_drop_flow_is_logged(drop, tmp_path, caplog):
    path = make_file(tmp_path, "a.exe")
    drop.guard.trusted.add(path)
    with caplog.at_level(logging.INFO, logger="src.api"):
        drop.api._handle_drop(drop_event(path))
        drop.api.add_dropped_shortcuts(drop.cat_id, [path])
    text = caplog.text
    for stage in ("[drop 2/5]", "[drop 4/5]", "[drop 5/5]"):
        assert stage in text, stage
    assert "OK" in text


def test_rejected_drop_logs_reason(drop, tmp_path, caplog):
    path = make_file(tmp_path, "a.exe")
    drop.guard.trusted.add(path)
    drop.api._handle_drop(drop_event(path))
    with caplog.at_level(logging.INFO, logger="src.api"):
        drop.api.add_dropped_shortcuts(None, [path])
    assert "drop 5/5" in caplog.text and "カテゴリーが分からない" in caplog.text


def test_drop_in_read_only_mode_reports_read_only(api_module, tmp_path, icon):
    """読み取り専用モードでドロップしても、既存の保存失敗（error_read_only）の表示になる"""
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{"config": {}, "categories": [')
    guard = mock.MagicMock(enabled=True)
    path = make_file(tmp_path, "game.exe")
    guard.consume.side_effect = _fake_consume({path})
    api = api_module.API(str(settings), drop_guard=guard)
    window = mock.MagicMock()
    api._attach_window(window)
    assert api.get_load_status()["read_only"] is True
    before = settings.read_bytes()

    api._handle_drop(drop_event(path))
    assert drop_payload(window)["files"] == [{"name": "game", "path": path}]
    cat_id = api.get_config()["categories"][0]["id"]
    assert api.add_dropped_shortcuts(cat_id, [path])["results"] == \
        [{"path": path, "ok": False, "error": "read_only"}]
    assert settings.read_bytes() == before


def test_select_file_uses_file_dialog_open(api, dialog, api_module):
    dialog.return_value = None
    api.select_file()
    assert dialog.call_args.args[0] == api_module.webview.FileDialog.OPEN
