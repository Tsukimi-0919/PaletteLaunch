"""src/core/config.py のテスト。ファイルはすべて tmp_path 上に作る（本物の settings.json には触れない）。"""
import datetime
import json
import logging
import os
import shutil
from pathlib import Path

import pytest

from src.core import config as config_module
from src.core.config import (
    ConfigManager,
    SchemaError,
    SettingsReadOnlyError,
    normalize_data,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "settings.json.example"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# v1.1.0 / v1.2.0 のタグの config.py を実際に動かして保存したファイル（CRLF, BOM なし）
OLD_VERSIONS = ["settings_v1.1.0.json", "settings_v1.2.0.json"]


@pytest.fixture
def manager(tmp_path):
    """一時フォルダ上の settings.json を使う ConfigManager（プロジェクト直下には書かない）"""
    return ConfigManager(str(tmp_path / "settings.json"), str(EXAMPLE))


@pytest.fixture
def today(monkeypatch):
    """日ごとのバックアップの「今日」を差し替える"""
    state = {"day": datetime.date(2026, 11, 9)}
    monkeypatch.setattr(config_module, "_today", lambda: state["day"])
    return state


def open_manager(tmp_path, content=None, bak=None, example=EXAMPLE):
    settings = tmp_path / "settings.json"
    if content is not None:
        settings.write_bytes(content)
    if bak is not None:
        (tmp_path / "settings.json.bak").write_bytes(bak)
    m = ConfigManager(str(settings), None if example is None else str(example))
    return m, settings


def dump(data):
    return json.dumps(data, indent=4, ensure_ascii=False).replace("\n", "\r\n").encode("utf-8")


def valid_settings(name="Saved"):
    return dump({"config": {"theme": "apex", "language": "en", "card_size": "small"},
                 "categories": [{"id": "c1", "name": name, "shortcuts": [
                     {"id": "s1", "name": "Game", "path": r"C:\Games\game.exe", "icon": ""}]}]})


def corrupt_copies(tmp_path):
    return sorted(p.name for p in tmp_path.glob("settings.corrupt-*.json"))


def leftovers(tmp_path):
    return sorted(p.name for p in tmp_path.glob("*.tmp"))


# --- 基本の操作 ---------------------------------------------------------------

def test_initial_structure(manager):
    """初期ロード時にconfigとcategoriesが分離された正しい構造になっているか"""
    data = manager.get_all()
    assert "config" in data
    assert "categories" in data
    assert data["config"]["theme"] == "valorant"
    assert data["config"]["language"] == "ja"
    # settings.json.example からコピーされる
    assert data["categories"][0]["name"] == "サンプルカテゴリ"


def test_update_setting(manager):
    """テーマと言語設定の更新ができるか"""
    manager.update_setting("theme", "hydrangea")
    manager.update_setting("language", "en")

    data = manager.get_all()
    assert data["config"]["theme"] == "hydrangea"
    assert data["config"]["language"] == "en"


def test_edit_category(manager):
    """カテゴリー名の変更ができるか"""
    data = manager.get_all()
    data["categories"][0]["name"] = "Updated Name"
    manager.save(data)

    assert manager.get_all()["categories"][0]["name"] == "Updated Name"


def test_add_and_delete_shortcut(manager):
    """ショートカットの追加と削除"""
    cat_id = manager.get_all()["categories"][0]["id"]

    manager.add_shortcut(cat_id, "Note", "notepad.exe", icon="base64_data")
    shortcuts = manager.get_all()["categories"][0]["shortcuts"]
    assert len(shortcuts) == 1
    assert shortcuts[0]["name"] == "Note"
    assert shortcuts[0]["icon"] == "base64_data"
    assert "target" not in shortcuts[0]

    manager.delete_shortcut(shortcuts[0]["id"])
    assert len(manager.get_all()["categories"][0]["shortcuts"]) == 0


def test_add_shortcut_keeps_original_path_and_target(manager):
    """path には登録したファイルをそのまま、解決先は target に保存する"""
    cat_id = manager.get_all()["categories"][0]["id"]
    manager.add_shortcut(cat_id, "Valorant", r"C:\Games\VALORANT.lnk",
                         icon="", target=r"C:\Riot Games\Riot Client\RiotClientServices.exe")
    s = manager.get_all()["categories"][0]["shortcuts"][0]
    assert s["path"] == r"C:\Games\VALORANT.lnk"
    assert s["target"] == r"C:\Riot Games\Riot Client\RiotClientServices.exe"


# --- パスの指定（#7） ----------------------------------------------------------

def test_config_path_must_be_absolute():
    with pytest.raises(ValueError):
        ConfigManager("settings.json")


def test_example_path_must_be_absolute(tmp_path):
    with pytest.raises(ValueError):
        ConfigManager(str(tmp_path / "settings.json"), "settings.json.example")


def test_missing_file_without_example_uses_default(tmp_path):
    m, settings = open_manager(tmp_path, example=None)
    assert settings.is_file()
    assert m.get_all()["categories"][0]["name"] == "General"
    assert m.get_status()["read_only"] is False


def test_missing_file_with_broken_example_uses_default(tmp_path):
    example = tmp_path / "example.json"
    example.write_bytes(b"{broken")
    (tmp_path / "app").mkdir()
    m, _ = open_manager(tmp_path / "app", example=example)
    assert m.get_all()["categories"][0]["name"] == "General"


def test_cannot_create_file_means_read_only(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(config_module, "atomic_write", fail)
    m, settings = open_manager(tmp_path)
    assert not settings.exists()
    assert m.get_status()["read_only"] is True
    assert m.get_status()["reason"] == "unwritable"


# --- 既存ユーザーの settings.json（v1.1.0 / v1.2.0） ----------------------------

@pytest.fixture(params=OLD_VERSIONS)
def old_file(request, tmp_path):
    src = FIXTURES / request.param
    dst = tmp_path / "settings.json"
    shutil.copyfile(src, dst)
    return request.param, src.read_bytes(), dst


def test_old_version_file_is_loaded_as_is(old_file):
    name, raw, path = old_file
    m = ConfigManager(str(path), str(EXAMPLE))
    assert m.get_status() == {"read_only": False, "reason": None,
                              "restored_from_backup": False, "corrupt_copy": None}
    assert m.get_all() == json.loads(raw.decode("utf-8"))
    assert path.read_bytes() == raw  # 読むだけでは書き換えない

    data = m.get_all()
    assert data["config"] == {"theme": "apex", "card_size": "small", "language": "en"}
    assert [c["name"] for c in data["categories"]] == ["サンプルカテゴリ", "ゲーム 🎮", 'Tools "&" <Utils>']
    game, tools = data["categories"][1]["shortcuts"], data["categories"][2]["shortcuts"]
    assert [s["name"] for s in game] == ["VALORANT", "Apex Legends"]
    assert [s["name"] for s in tools] == ["Notepad（メモ帳）", "起動スクリプト"]
    assert all(s["icon"].startswith("data:image/webp;base64,") for s in game + tools[:1])
    assert tools[1]["icon"] == ""
    if name == "settings_v1.2.0.json":
        assert game[0]["path"] == r"C:\Users\Public\Desktop\VALORANT.lnk"
        assert game[0]["target"] == r"C:\Riot Games\Riot Client\RiotClientServices.exe"
        assert game[1]["target"] == "steam://rungameid/1172470"
        assert "target" not in tools[0]
    else:
        assert game[0]["path"] == r"C:\Riot Games\Riot Client\RiotClientServices.exe"
        assert game[1]["path"] == "steam://rungameid/1172470"
        assert all("target" not in s for s in game + tools)


def test_old_version_file_is_saved_in_the_same_format(old_file):
    """変更せずに保存するとバイト列が一致する（旧バージョンと同じ形式で書く）"""
    _, raw, path = old_file
    m = ConfigManager(str(path), str(EXAMPLE))
    m.save(m.get_all())
    assert path.read_bytes() == raw


def test_old_version_file_keeps_everything_else_after_a_change(old_file, today):
    _, raw, path = old_file
    m = ConfigManager(str(path), str(EXAMPLE))
    m.update_setting("language", "ja")

    expected = json.loads(raw.decode("utf-8"))
    expected["config"]["language"] = "ja"
    assert m.get_all() == expected
    # 保存前のファイルがそのままバックアップに残る
    assert (path.parent / "settings.json.bak").read_bytes() == raw
    assert (path.parent / "settings.20261109.bak.json").read_bytes() == raw


def test_saved_file_is_readable_by_old_versions(old_file):
    """旧バージョンの読み込み（open(encoding='utf-8') + json.load）で読めること"""
    _, raw, path = old_file
    m = ConfigManager(str(path), str(EXAMPLE))
    cat_id = m.get_all()["categories"][0]["id"]
    m.add_shortcut(cat_id, "New", r"C:\Games\new.exe", icon="", target=None)
    saved = path.read_bytes()
    assert not saved.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in saved and saved.count(b"\n") == saved.count(b"\r\n")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["categories"][0]["shortcuts"][-1]["name"] == "New"
    assert set(data) == {"config", "categories"}


def test_disallowed_values_from_old_versions_are_kept(tmp_path):
    """許可外の値（以前の「大」サイズ等）は書き換えない（表示側で正規化する）"""
    raw = dump({"config": {"theme": "valorant", "card_size": "large", "language": "fr"},
                "categories": []})
    m, path = open_manager(tmp_path, raw)
    assert m.get_all()["config"] == {"theme": "valorant", "card_size": "large", "language": "fr"}
    m.save(m.get_all())
    assert path.read_bytes() == raw


def test_file_with_bom_is_readable(tmp_path):
    m, _ = open_manager(tmp_path, b"\xef\xbb\xbf" + valid_settings())
    assert m.get_status()["read_only"] is False
    assert m.get_all()["categories"][0]["name"] == "Saved"


# --- 壊れたファイル（#1, #3） ----------------------------------------------------

BROKEN = [
    pytest.param(b'{"config": {"theme": "apex"}, "categories": [', id="truncated"),
    pytest.param(b"\xff\xfe\x00garbage", id="not-utf8"),
    pytest.param(b"[1, 2, 3]", id="top-level-list"),
    pytest.param(b"null", id="null"),
    pytest.param(b'{"config": {}, "categories": "abc"}', id="categories-not-list"),
]


@pytest.mark.parametrize("content", BROKEN)
def test_broken_file_without_backup_is_read_only(tmp_path, content):
    m, path = open_manager(tmp_path, content)
    status = m.get_status()
    assert status["read_only"] is True
    assert status["reason"] == "corrupt"
    assert status["restored_from_backup"] is False

    # 壊れたファイルは退避され、元の場所にもそのまま残る
    assert corrupt_copies(tmp_path) == [status["corrupt_copy"]]
    assert (tmp_path / status["corrupt_copy"]).read_bytes() == content
    assert path.read_bytes() == content

    # 表示は初期値。保存はすべて拒否され、ファイルは変わらない
    assert m.get_all()["categories"][0]["name"] == "General"
    cat_id = m.get_all()["categories"][0]["id"]
    with pytest.raises(SettingsReadOnlyError):
        m.save(m.get_all())
    for call in (lambda: m.update_setting("theme", "apex"),
                 lambda: m.add_category("x"),
                 lambda: m.delete_category(cat_id),
                 lambda: m.add_shortcut(cat_id, "a", r"C:\a.exe"),
                 lambda: m.update_shortcut("s", name="b"),
                 lambda: m.delete_shortcut("s")):
        with pytest.raises(SettingsReadOnlyError):
            call()
    assert path.read_bytes() == content
    assert not (tmp_path / "settings.json.bak").exists()
    assert not list(tmp_path.glob("settings.*.bak.json"))


@pytest.mark.parametrize("content", BROKEN)
def test_broken_file_is_restored_from_backup(tmp_path, content):
    bak = valid_settings("FromBackup")
    m, path = open_manager(tmp_path, content, bak=bak)
    status = m.get_status()
    assert status["read_only"] is False
    assert status["restored_from_backup"] is True
    assert status["reason"] == "corrupt"
    assert path.read_bytes() == bak
    assert (tmp_path / status["corrupt_copy"]).read_bytes() == content
    assert m.get_all()["categories"][0]["name"] == "FromBackup"


def test_broken_file_and_broken_backup_is_read_only(tmp_path):
    m, path = open_manager(tmp_path, b"{broken", bak=b"{also broken")
    assert m.get_status()["read_only"] is True
    assert path.read_bytes() == b"{broken"
    assert (tmp_path / "settings.json.bak").read_bytes() == b"{also broken"


def test_corrupt_copy_name_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "_now", lambda: datetime.datetime(2026, 11, 9, 12, 34, 56))
    open_manager(tmp_path, b"{first")
    (tmp_path / "settings.json").write_bytes(b"{second")
    open_manager(tmp_path, None)
    assert corrupt_copies(tmp_path) == ["settings.corrupt-20261109-123456-1.json",
                                        "settings.corrupt-20261109-123456.json"]
    assert (tmp_path / "settings.corrupt-20261109-123456.json").read_bytes() == b"{first"


@pytest.fixture
def clock(monkeypatch):
    """退避ファイルの名前に使う「今」を、呼ぶたびに 1 秒進める"""
    state = {"now": datetime.datetime(2026, 11, 10, 9, 0, 0)}

    def now():
        state["now"] += datetime.timedelta(seconds=1)
        return state["now"]

    monkeypatch.setattr(config_module, "_now", now)
    return state


def test_same_corrupt_content_is_not_copied_twice(tmp_path, clock):
    """壊れたまま（.bak も無く読み取り専用で）起動し直しても、同じ内容の退避ファイルは増えない"""
    m1, _ = open_manager(tmp_path, b"{broken")
    first = m1.get_status()["corrupt_copy"]
    m2, path = open_manager(tmp_path, None)
    assert m2.get_status()["read_only"] is True
    # 通知は既存の退避ファイルを指す
    assert m2.get_status()["corrupt_copy"] == first
    assert corrupt_copies(tmp_path) == [first]
    assert path.read_bytes() == b"{broken"


def test_same_content_found_among_older_copies(tmp_path, clock):
    """いちばん新しいものでなくても、同じ内容の退避ファイルがあれば作らない"""
    open_manager(tmp_path, b"{A")
    (tmp_path / "settings.json").write_bytes(b"{B")
    open_manager(tmp_path, None)
    before = corrupt_copies(tmp_path)
    (tmp_path / "settings.json").write_bytes(b"{A")
    m, _ = open_manager(tmp_path, None)
    assert corrupt_copies(tmp_path) == before
    assert (tmp_path / m.get_status()["corrupt_copy"]).read_bytes() == b"{A"


def test_same_size_different_content_is_copied(tmp_path, clock):
    open_manager(tmp_path, b"{AAAA")
    (tmp_path / "settings.json").write_bytes(b"{BBBB")
    m, _ = open_manager(tmp_path, None)
    assert len(corrupt_copies(tmp_path)) == 2
    assert (tmp_path / m.get_status()["corrupt_copy"]).read_bytes() == b"{BBBB"


def test_same_content_while_running_is_not_copied_twice(tmp_path, clock):
    """起動時に退避したのと同じ内容に、起動後に壊れても増えない"""
    open_manager(tmp_path, b"{broken")
    path = tmp_path / "settings.json"
    path.write_bytes(valid_settings())
    m, _ = open_manager(tmp_path, None)
    path.write_bytes(b"{broken")
    m.get_all()
    assert m.get_status()["read_only"] is True
    assert len(corrupt_copies(tmp_path)) == 1


def test_corrupt_copies_keep_newest_ten(tmp_path, clock):
    assert config_module.CORRUPT_COPY_KEEP == 10
    for i in range(12):
        (tmp_path / "settings.json").write_bytes(b"{broken %d" % i)
        m, _ = open_manager(tmp_path, None)
        assert (tmp_path / m.get_status()["corrupt_copy"]).is_file()

    names = corrupt_copies(tmp_path)
    assert len(names) == 10
    contents = sorted((tmp_path / n).read_bytes() for n in names)
    assert contents == sorted(b"{broken %d" % i for i in range(2, 12))
    # 新しい順に並ぶ
    listed = [os.path.basename(p) for p in m.list_corrupt_copies()]
    assert listed == sorted(names, reverse=True)
    assert listed[0] == m.get_status()["corrupt_copy"]


def test_corrupt_copy_order_uses_name_not_mtime(tmp_path, clock):
    """新旧はファイル名の日時と連番で決める（更新日時は元ファイルのものが引き継がれるため使わない）"""
    for i in range(9):
        name = f"settings.corrupt-20200101-0000{i:02d}.json"
        (tmp_path / name).write_bytes(b"{old %d" % i)
    # 同じ秒の連番つき（-1 の方が新しい）
    (tmp_path / "settings.corrupt-20200101-000009.json").write_bytes(b"{old 9")
    (tmp_path / "settings.corrupt-20200101-000009-1.json").write_bytes(b"{old 9-1")
    # 更新日時は古いものほど新しくしておく
    for p in tmp_path.glob("settings.corrupt-*.json"):
        os.utime(p, (2_000_000_000, 2_000_000_000))

    (tmp_path / "settings.json").write_bytes(b"{new")
    m, _ = open_manager(tmp_path, None)
    names = corrupt_copies(tmp_path)
    assert len(names) == 10
    assert "settings.corrupt-20200101-000000.json" not in names
    assert "settings.corrupt-20200101-000001.json" not in names
    assert "settings.corrupt-20200101-000009-1.json" in names
    assert m.get_status()["corrupt_copy"] in names


def test_prune_ignores_other_names(tmp_path, clock):
    others = ["settings.corrupt-old.json", "settings.corrupt-20200101.json",
              "other.corrupt-20200101-000000.json", "settings.corrupt-20200101-000000.txt",
              "settings.json.bak", "settings.20200101.bak.json"]
    for name in others:
        (tmp_path / name).write_bytes(b"keep")
    for i in range(12):
        (tmp_path / "settings.json").write_bytes(b"{broken %d" % i)
        open_manager(tmp_path, None)
    for name in others:
        assert (tmp_path / name).read_bytes() == b"keep"


def test_prune_failure_does_not_stop_startup(tmp_path, clock, monkeypatch, caplog):
    for i in range(10):
        (tmp_path / f"settings.corrupt-20200101-0000{i:02d}.json").write_bytes(b"{old %d" % i)
    (tmp_path / "settings.json.bak").write_bytes(valid_settings("FromBak"))

    def fail(path):
        raise PermissionError(13, "in use", path)

    monkeypatch.setattr(config_module.os, "remove", fail)
    (tmp_path / "settings.json").write_bytes(b"{new")
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        m, _ = open_manager(tmp_path, None)
    status = m.get_status()
    assert status["restored_from_backup"] is True
    assert (tmp_path / status["corrupt_copy"]).read_bytes() == b"{new"
    assert m.get_all()["categories"][0]["name"] == "FromBak"
    assert len(corrupt_copies(tmp_path)) == 11
    assert "古い退避ファイルを削除できません" in caplog.text


def test_corrupt_copy_compare_read_failure_still_copies(tmp_path, clock, monkeypatch):
    """既存の退避ファイルが読めなくても（ロック中など）、新しく退避する"""
    open_manager(tmp_path, b"{broken")
    first = corrupt_copies(tmp_path)[0]
    real_read = ConfigManager._read_raw

    def read(self, p):
        if os.path.basename(p) == first:
            raise PermissionError(13, "locked")
        return real_read(self, p)

    monkeypatch.setattr(ConfigManager, "_read_raw", read)
    m, _ = open_manager(tmp_path, None)
    assert len(corrupt_copies(tmp_path)) == 2
    assert m.get_status()["corrupt_copy"] != first


def test_read_only_data_is_a_copy(tmp_path):
    m, _ = open_manager(tmp_path, b"{broken")
    m.get_all()["categories"].clear()
    assert len(m.get_all()["categories"]) == 1


def test_unreadable_file_is_read_only_without_copy(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_bytes(valid_settings())
    real_read = ConfigManager._read_raw

    def read(self, p):
        if p == str(path):
            raise PermissionError(13, "The process cannot access the file")
        return real_read(self, p)

    monkeypatch.setattr(ConfigManager, "_read_raw", read)
    m = ConfigManager(str(path), str(EXAMPLE))
    assert m.get_status()["read_only"] is True
    assert m.get_status()["reason"] == "unreadable"
    assert corrupt_copies(tmp_path) == []
    with pytest.raises(SettingsReadOnlyError):
        m.save(m.get_all())
    assert path.read_bytes() == valid_settings()


def test_file_broken_while_running_stops_saving(tmp_path):
    """起動後に壊れた場合も、初期値で上書きせずに読み取り専用にする"""
    m, path = open_manager(tmp_path, valid_settings())
    path.write_bytes(b"{broken later")
    data = m.get_all()
    assert m.get_status()["read_only"] is True
    with pytest.raises(SettingsReadOnlyError):
        m.save(data)
    assert path.read_bytes() == b"{broken later"
    assert (tmp_path / m.get_status()["corrupt_copy"]).read_bytes() == b"{broken later"


def test_file_deleted_while_running_stops_saving(tmp_path):
    m, path = open_manager(tmp_path, valid_settings())
    path.unlink()
    m.get_all()
    assert m.get_status() == {"read_only": True, "reason": "unreadable",
                              "restored_from_backup": False, "corrupt_copy": None}


# --- 空ファイル ---------------------------------------------------------------

@pytest.mark.parametrize("content", [b"", b"  \r\n\t", b"\xef\xbb\xbf"],
                         ids=["zero-bytes", "whitespace", "bom-only"])
def test_empty_file_is_recreated_from_example(tmp_path, content):
    m, path = open_manager(tmp_path, content)
    assert m.get_status() == {"read_only": False, "reason": "empty",
                              "restored_from_backup": False, "corrupt_copy": None}
    assert m.get_all()["categories"][0]["name"] == "サンプルカテゴリ"
    assert json.loads(path.read_text(encoding="utf-8"))["categories"][0]["name"] == "サンプルカテゴリ"
    assert corrupt_copies(tmp_path) == []


def test_empty_file_is_restored_from_backup(tmp_path):
    bak = valid_settings("FromBackup")
    m, path = open_manager(tmp_path, b"", bak=bak)
    assert m.get_status()["restored_from_backup"] is True
    assert m.get_status()["reason"] == "empty"
    assert path.read_bytes() == bak


def test_empty_file_with_broken_backup_is_recreated(tmp_path):
    m, _ = open_manager(tmp_path, b"", bak=b"{broken")
    assert m.get_status()["read_only"] is False
    assert m.get_all()["categories"][0]["name"] == "サンプルカテゴリ"


# --- スキーマの補完（#6） ------------------------------------------------------

def test_missing_config_key_is_completed(tmp_path):
    m, _ = open_manager(tmp_path, dump({"categories": [{"id": "c", "name": "A", "shortcuts": []}]}))
    data = m.get_all()
    assert data["config"] == {"theme": "valorant", "language": "ja", "card_size": "medium"}
    assert data["categories"][0]["name"] == "A"


def test_legacy_top_level_settings_move_into_config(tmp_path):
    m, _ = open_manager(tmp_path, dump({"theme": "apex", "categories": []}))
    assert m.get_all()["config"]["theme"] == "apex"


def test_missing_card_size_is_completed(tmp_path):
    """v1.0.0 の形式（card_size なし）"""
    m, _ = open_manager(tmp_path, dump({"config": {"theme": "apex", "language": "en"},
                                         "categories": []}))
    assert m.get_all()["config"] == {"theme": "apex", "language": "en", "card_size": "medium"}


def test_missing_categories_is_completed(tmp_path):
    m, _ = open_manager(tmp_path, dump({"config": {"theme": "apex"}}))
    assert m.get_status()["read_only"] is False
    assert m.get_all()["categories"] == []


def test_missing_ids_are_completed_with_stable_ids(tmp_path):
    raw = dump({"config": {}, "categories": [
        {"name": "A", "shortcuts": [{"name": "x", "path": r"C:\x.exe", "icon": ""}]}]})
    m, _ = open_manager(tmp_path, raw)
    first, second = m.get_all(), m.get_all()
    cat_id = first["categories"][0]["id"]
    item_id = first["categories"][0]["shortcuts"][0]["id"]
    assert cat_id and item_id and cat_id != item_id
    # 保存していなくても、読むたびに同じ id になる（UI から id で操作できる）
    assert second["categories"][0]["id"] == cat_id
    m.delete_shortcut(item_id)
    assert m.get_all()["categories"][0]["shortcuts"] == []


def test_duplicate_ids_are_renamed(tmp_path):
    raw = dump({"config": {}, "categories": [
        {"id": "dup", "name": "A", "shortcuts": [
            {"id": "dup", "name": "x", "path": "", "icon": ""},
            {"id": "s", "name": "y", "path": "", "icon": ""},
            {"id": "s", "name": "z", "path": "", "icon": ""}]}]})
    m, _ = open_manager(tmp_path, raw)
    data = m.get_all()
    ids = [data["categories"][0]["id"]] + [s["id"] for s in data["categories"][0]["shortcuts"]]
    assert len(set(ids)) == 4
    assert ids[0] == "dup" and ids[2] == "s"


def test_unknown_keys_are_kept(tmp_path):
    raw = dump({"config": {"theme": "apex", "future": 1}, "extra": {"a": [1]},
                "categories": [{"id": "c", "name": "A", "color": "red", "shortcuts": [
                    {"id": "s", "name": "x", "path": "", "icon": "", "args": "-x"}]}]})
    m, path = open_manager(tmp_path, raw)
    m.update_setting("language", "en")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["extra"] == {"a": [1]}
    assert data["config"]["future"] == 1
    assert data["categories"][0]["color"] == "red"
    assert data["categories"][0]["shortcuts"][0]["args"] == "-x"


def test_invalid_elements_are_dropped_and_fields_completed(tmp_path):
    raw = dump({"config": "bad", "categories": [
        "not a category", {"id": "c", "name": 5},
        {"id": "d", "shortcuts": [None, {"id": "s", "name": None, "path": 3}]}]})
    m, _ = open_manager(tmp_path, raw)
    data = m.get_all()
    assert data["config"]["theme"] == "valorant"
    assert [c["id"] for c in data["categories"]] == ["c", "d"]
    assert data["categories"][0] == {"id": "c", "name": "5", "shortcuts": []}
    assert data["categories"][1]["name"] == ""
    assert data["categories"][1]["shortcuts"] == [{"id": "s", "name": "", "path": "", "icon": ""}]


def test_normalize_does_not_modify_input():
    data = {"categories": [{"name": "A"}]}
    normalize_data(data)
    assert data == {"categories": [{"name": "A"}]}


@pytest.mark.parametrize("data", [[], None, "x", {"categories": {}}])
def test_normalize_rejects_wrong_shapes(data):
    with pytest.raises(SchemaError):
        normalize_data(data)


def test_save_rejects_wrong_shape_without_writing(manager, tmp_path):
    path = tmp_path / "settings.json"
    before = path.read_bytes()
    with pytest.raises(ValueError):
        manager.save({"categories": "x"})
    assert path.read_bytes() == before


# --- default_data のコピー（#4） -----------------------------------------------

def test_default_data_is_copied(tmp_path):
    m, _ = open_manager(tmp_path, example=None)
    m.default_data["categories"].clear()
    m.default_data["config"]["theme"] = "x"
    assert m.default_data["categories"][0]["name"] == "General"
    assert m.default_data["config"]["theme"] == "valorant"
    assert config_module.DEFAULT_CONFIG["theme"] == "valorant"


def test_get_all_returns_new_objects(manager):
    manager.get_all()["categories"].clear()
    assert manager.get_all()["categories"]


# --- 原子的な書き込み（#2） ----------------------------------------------------

def _break(monkeypatch, target, name):
    def fail(*_args, **_kwargs):
        raise OSError(5, f"{name} failed")
    monkeypatch.setattr(target, name, fail)


@pytest.mark.parametrize("target, name", [
    (config_module.os, "fsync"),
    (config_module.os, "replace"),
    (config_module.tempfile, "mkstemp"),
])
def test_failed_write_keeps_original(tmp_path, monkeypatch, target, name):
    m, path = open_manager(tmp_path, valid_settings())
    data = m.get_all()
    data["categories"][0]["name"] = "Changed"
    monkeypatch.setattr(config_module, "_REPLACE_WAIT", 0)
    _break(monkeypatch, target, name)
    with pytest.raises(OSError):
        m.save(data)
    assert path.read_bytes() == valid_settings()
    assert leftovers(tmp_path) == []


def test_exception_while_dumping_keeps_original(tmp_path, monkeypatch):
    m, path = open_manager(tmp_path, valid_settings())
    expected = valid_settings()

    def fail(*_args, **_kwargs):
        raise TypeError("not serializable")
    monkeypatch.setattr(config_module.json, "dumps", fail)
    with pytest.raises(TypeError):
        m.save(m.get_all())
    monkeypatch.undo()
    assert path.read_bytes() == expected
    assert leftovers(tmp_path) == []


def test_exception_in_the_middle_of_writing_keeps_original(tmp_path, monkeypatch):
    """書き込みの途中（一部だけ書いたところ）で落ちても、元のファイルは残る"""
    m, path = open_manager(tmp_path, valid_settings())
    real_write = config_module.atomic_write

    def half_write(target, writer):
        def broken(f):
            f.write(b'{"config": ')
            raise KeyboardInterrupt
        real_write(target, broken if target == str(path) else writer)

    monkeypatch.setattr(config_module, "atomic_write", half_write)
    data = m.get_all()
    data["categories"].clear()
    with pytest.raises(KeyboardInterrupt):
        m.save(data)
    assert path.read_bytes() == valid_settings()
    assert leftovers(tmp_path) == []


def test_replace_is_retried_when_file_is_locked(tmp_path, monkeypatch):
    m, path = open_manager(tmp_path, valid_settings())
    real_replace = os.replace
    calls = {"n": 0}

    def replace(src, dst):
        calls["n"] += 1
        if dst == str(path) and calls["n"] <= 2:
            raise PermissionError(13, "locked")
        real_replace(src, dst)

    monkeypatch.setattr(config_module.os, "replace", replace)
    monkeypatch.setattr(config_module, "_REPLACE_WAIT", 0)
    m.update_setting("theme", "valorant")
    assert m.get_all()["config"]["theme"] == "valorant"


# --- .bak（1つ前の保存） --------------------------------------------------------

def test_bak_is_previous_save(manager, tmp_path):
    manager.update_setting("theme", "first")
    after_first = (tmp_path / "settings.json").read_bytes()
    manager.update_setting("theme", "second")
    assert (tmp_path / "settings.json.bak").read_bytes() == after_first


def test_broken_current_file_does_not_overwrite_backups(tmp_path, today):
    """保存直前のファイルが壊れていたら、.bak も日ごとのバックアップも作らない"""
    m, path = open_manager(tmp_path, valid_settings("Current"), bak=valid_settings("Older"))
    data = m.get_all()
    path.write_bytes(b"{broken just before save")
    m.save(data)
    assert (tmp_path / "settings.json.bak").read_bytes() == valid_settings("Older")
    assert not (tmp_path / "settings.20261109.bak.json").exists()
    assert m.get_all()["categories"][0]["name"] == "Current"


def test_bak_failure_does_not_stop_saving(tmp_path, monkeypatch, caplog):
    m, path = open_manager(tmp_path, valid_settings())
    real_write = config_module.atomic_write

    def write(target, writer):
        if target.endswith(".bak") or target.endswith(".bak.json"):
            raise PermissionError(13, "denied")
        real_write(target, writer)

    monkeypatch.setattr(config_module, "atomic_write", write)
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        m.update_setting("theme", "valorant")
    assert m.get_all()["config"]["theme"] == "valorant"
    assert "settings.json.bak" in caplog.text
    assert "日ごとのバックアップ" in caplog.text


# --- 日ごとのバックアップ -------------------------------------------------------

def test_daily_backup_is_created_once_per_day(tmp_path, today):
    m, _ = open_manager(tmp_path, valid_settings("Day1-start"))
    m.update_setting("theme", "a")
    m.update_setting("theme", "b")
    daily = tmp_path / "settings.20261109.bak.json"
    # その日の最初の保存の前の状態
    assert daily.read_bytes() == valid_settings("Day1-start")

    today["day"] = datetime.date(2026, 11, 10)
    before = (tmp_path / "settings.json").read_bytes()
    m.update_setting("theme", "c")
    assert (tmp_path / "settings.20261110.bak.json").read_bytes() == before
    assert daily.read_bytes() == valid_settings("Day1-start")


def test_daily_backups_keep_seven_generations(tmp_path, today):
    m, _ = open_manager(tmp_path, valid_settings())
    others = ["settings.json.bak", "settings.corrupt-20200101-000000.json",
              "other.20200101.bak.json", "settings.2020.bak.json", "settings.20200101.bak.txt"]
    for name in others:
        (tmp_path / name).write_bytes(b"keep")

    start = datetime.date(2026, 11, 1)
    for i in range(10):
        today["day"] = start + datetime.timedelta(days=i)
        m.update_setting("theme", f"t{i}")

    names = [os.path.basename(p) for p in m.list_daily_backups()]
    assert names == [f"settings.{(start + datetime.timedelta(days=i)):%Y%m%d}.bak.json"
                     for i in range(9, 2, -1)]
    for name in others[1:]:
        assert (tmp_path / name).read_bytes() == b"keep"


def test_daily_backup_failure_does_not_stop_saving(tmp_path, today, monkeypatch, caplog):
    m, _ = open_manager(tmp_path, valid_settings())

    def fail(self, raw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ConfigManager, "_make_daily_backup", fail)
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        m.update_setting("theme", "valorant")
    assert m.get_all()["config"]["theme"] == "valorant"
    assert "日ごとのバックアップを作成できません" in caplog.text


def test_daily_backup_prune_failure_does_not_stop_saving(tmp_path, today, monkeypatch, caplog):
    m, _ = open_manager(tmp_path, valid_settings())
    for i in range(1, 9):
        (tmp_path / f"settings.202610{i:02d}.bak.json").write_bytes(b"old")

    def fail(_path):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(config_module.os, "remove", fail)
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        m.update_setting("theme", "valorant")
    assert m.get_all()["config"]["theme"] == "valorant"
    assert (tmp_path / "settings.20261109.bak.json").exists()
    assert "古いバックアップを削除できません" in caplog.text


def test_daily_backup_is_a_valid_settings_file(tmp_path, today):
    """日ごとのバックアップは、settings.json に名前を変えればそのまま使える（docs/backup.md）"""
    m, _ = open_manager(tmp_path, valid_settings("Backup"))
    m.update_setting("theme", "x")
    restored = tmp_path / "restored"
    restored.mkdir()
    shutil.copyfile(tmp_path / "settings.20261109.bak.json", restored / "settings.json")
    m2 = ConfigManager(str(restored / "settings.json"), str(EXAMPLE))
    assert m2.get_status()["read_only"] is False
    assert m2.get_all()["categories"][0]["name"] == "Backup"
