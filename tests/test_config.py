import pytest
from src.core.config import ConfigManager


@pytest.fixture
def manager(tmp_path):
    """一時フォルダ上の settings.json を使う ConfigManager（プロジェクト直下には書かない）"""
    return ConfigManager(str(tmp_path / "settings.json"))


def test_initial_structure(manager):
    """初期ロード時にconfigとcategories가 分離された正しい構造になっているか"""
    data = manager.get_all()
    # 構造の確認
    assert "config" in data
    assert "categories" in data
    # デフォルト値の確認
    assert data["config"]["theme"] == "valorant"
    assert data["config"]["language"] == "ja"

    # 期待値を 'General' から 'サンプルカテゴリ' に修正
    assert data["categories"][0]["name"] == "サンプルカテゴリ"


def test_update_setting(manager):
    """テーマと言語設定の更新ができるか"""
    manager.update_setting("theme", "hydrangea")
    manager.update_setting("language", "en")

    data = manager.get_all()
    assert data["config"]["theme"] == "hydrangea"
    assert data["config"]["language"] == "en"


def test_edit_category(manager):
    """カテゴリー名の変更ができるか（新機能）"""
    # カテゴリー名の更新
    data = manager._get_raw_data()
    data["categories"][0]["name"] = "Updated Name"
    manager.save(data)

    assert manager.get_all()["categories"][0]["name"] == "Updated Name"


def test_add_and_delete_shortcut(manager):
    """ショートカットの追加と削除（新しいデータ構造に対応）"""
    cat_id = manager.get_all()["categories"][0]["id"]

    # 追加
    manager.add_shortcut(cat_id, "Note", "notepad.exe", icon="base64_data")
    data = manager.get_all()
    shortcuts = data["categories"][0]["shortcuts"]
    assert len(shortcuts) == 1
    assert shortcuts[0]["name"] == "Note"
    assert shortcuts[0]["icon"] == "base64_data"

    # 削除
    short_id = shortcuts[0]["id"]
    manager.delete_shortcut(short_id)
    assert len(manager.get_all()["categories"][0]["shortcuts"]) == 0
