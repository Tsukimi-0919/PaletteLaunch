"""
UIからのリクエストを受け取り、設定管理やアプリ起動を制御するAPIモジュール。

注意: js_api に渡したオブジェクトは、"_" で始まらない属性・メソッドが
入れ子のオブジェクトも含めてすべて JS から呼べる（pywebview 6.1）。
内部用の属性・メソッドには必ず "_" を付けること。
"""
import logging
import os
import re
import sys
import uuid

import webview

from src.core.config import ConfigManager, SettingsReadOnlyError
from src.core.icons import get_icon_base64
from src.core.launcher import (
    get_lnk_info,
    is_allowed_url,
    is_missing_drive_target,
    is_unc_path,
    launch_app,
    parse_icon_location,
    read_url_file,
    read_url_target,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".exe", ".lnk", ".url", ".bat")
NAME_MAX_LENGTH = 100
ALLOWED_LANGUAGES = ("ja", "en")
ALLOWED_CARD_SIZES = ("small", "medium")

# 制御文字（C0/C1）と、文字の向きを変える制御文字
_UNSAFE_CHARS_RE = re.compile(
    "[\u0000-\u001f\u007f-\u009f‪-‮⁦-⁩]")


def _clean_name(name):
    """表示名を正規化する。不正なら None"""
    if not isinstance(name, str):
        return None
    cleaned = _UNSAFE_CHARS_RE.sub("", name).strip()[:NAME_MAX_LENGTH].strip()
    return cleaned or None


def _normalize_path(path):
    return os.path.normcase(os.path.abspath(path))


def _error(code):
    return {"ok": False, "error": code}


def _is_valid_order(categories_order):
    """save_order の引数: [{"id": str, "shortcuts": [str, ...]}, ...]"""
    if not isinstance(categories_order, list):
        return False
    for info in categories_order:
        if not isinstance(info, dict) or not isinstance(info.get("id"), str):
            return False
        items = info.get("shortcuts")
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            return False
    return True


class API:
    """
    フロントエンド(JavaScript)とバックエンド(Python)を仲介するクラス。
    """

    def __init__(self, settings_path, example_path=None):
        """settings_path, example_path は絶対パス（main.py で解決する）"""
        self._settings_path = settings_path
        # 設定ファイルの管理クラスをインスタンス化
        self._config = ConfigManager(self._settings_path, example_path)
        # 最後に select_file で選ばれたパス（正規化済み）。これ以外は登録させない
        self._selected_path = None

    def _save(self, save, *args):
        """
        保存処理を実行する。成功なら None、失敗ならエラーコードを返す。
        読み取り専用モードの拒否と書き込みの失敗はここで受け止める（元のファイルは変わらない）。
        """
        try:
            save(*args)
            return None
        except SettingsReadOnlyError:
            logger.warning("読み取り専用モードのため保存を拒否しました")
            return "read_only"
        except (OSError, ValueError) as e:
            logger.error("設定を保存できません: %s", e)
            return "save_failed"

    def get_load_status(self):
        """
        起動時の設定ファイルの読み込み結果を返す（UI が起動時に知らせる用）。
        {"read_only", "reason", "restored_from_backup", "corrupt_copy"(ファイル名のみ)}
        """
        return self._config.get_status()

    def update_setting(self, key, value):
        """テーマ・言語・カードサイズを許可リストで検証して保存する"""
        if key == "theme":
            allowed = self.get_themes()
        elif key == "language":
            allowed = ALLOWED_LANGUAGES
        elif key == "card_size":
            allowed = ALLOWED_CARD_SIZES
        else:
            logger.warning("設定更新を拒否: 不明なキー %r", key)
            return False

        if not isinstance(value, str) or value not in allowed:
            logger.warning("設定更新を拒否: %s=%r", key, value)
            return False

        return self._save(self._config.update_setting, key, value) is None

    def get_config(self):
        """現在の全設定をUIに返す"""
        return self._config.get_all()

    def add_category(self, name):
        """新しいカテゴリーを追加する"""
        name = _clean_name(name)
        if name is None:
            return False

        data = self._config.get_all()
        new_cat = {
            "id": str(uuid.uuid4()),
            "name": name,
            "shortcuts": []
        }
        data["categories"].append(new_cat)
        return self._save(self._config.save, data) is None

    def delete_category(self, category_id):
        """カテゴリーを削除する"""
        if not isinstance(category_id, str):
            return False
        data = self._config.get_all()
        data["categories"] = [
            c for c in data["categories"] if c["id"] != category_id]
        return self._save(self._config.save, data) is None

    def _validate_new_shortcut(self, path):
        """
        登録しようとしているパスを検証する。
        OK なら (None, 解決先) 、NG なら (エラーコード, None) を返す。
        """
        if not isinstance(path, str) or not path:
            return "invalid_path", None
        # UNC は存在チェックだけで SMB 接続が発生するため最初に弾く
        if is_unc_path(path):
            return "unc_not_allowed", None

        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return "extension_not_allowed", None

        if self._selected_path is None or _normalize_path(path) != self._selected_path:
            return "path_not_selected", None

        if not os.path.isfile(path):
            return "file_not_found", None

        if ext == ".lnk":
            info = get_lnk_info(path)
            target = (info or {}).get("target", "")
            if is_unc_path(target):
                return "unc_not_allowed", None
            if is_missing_drive_target(target):
                return "target_not_found", None
            return None, target or path

        if ext == ".url":
            url = read_url_target(path)
            if not url or not is_allowed_url(url):
                return "url_not_allowed", None
            return None, url

        return None, path

    def _get_shortcut_icon(self, path, target):
        """アイコンを候補の順に試して取得する（UNC は get_icon_base64 側で拒否）"""
        candidates = []
        ext = os.path.splitext(path)[1].lower()

        if ext == ".lnk":
            # 1. ショートカットの IconLocation（インデックス付き）
            info = get_lnk_info(path)
            location = parse_icon_location((info or {}).get("icon_location"))
            if location:
                candidates.append(location)
        elif ext == ".url":
            # 1. .url の IconFile
            config = read_url_file(path)
            if config is not None and config.has_option('InternetShortcut', 'IconFile'):
                # 「,0」などのインデックス指定を外し、環境変数を展開する
                location = parse_icon_location(
                    config.get('InternetShortcut', 'IconFile'))
                if location:
                    candidates.append((location[0], 0))

        # 2. 解決先（exe 等）、3. 元のファイル
        if target and target != path:
            candidates.append((target, 0))
        candidates.append((path, 0))

        for icon_path, index in candidates:
            icon_data = get_icon_base64(icon_path, index)
            if icon_data:
                return icon_data
        return ""

    def add_shortcut(self, category_id, name, path):
        """
        ショートカットを追加する。
        戻り値: {"ok": True} または {"ok": False, "error": "<エラーコード>"}
        """
        if not isinstance(category_id, str):
            return _error("category_not_found")

        error, target = self._validate_new_shortcut(path)
        if error:
            logger.warning("ショートカット登録を拒否 (%s): %r", error, path)
            return _error(error)

        name = _clean_name(name)
        if name is None:
            return _error("invalid_name")

        data = self._config.get_all()
        if not any(c["id"] == category_id for c in data["categories"]):
            return _error("category_not_found")

        icon_data = self._get_shortcut_icon(path, target)

        # 起動用には登録したファイルのパスをそのまま、解決先は表示用に target へ保存する
        error = self._save(lambda: self._config.add_shortcut(
            category_id, name, path, icon=icon_data,
            target=target if target != path else None))
        if error:
            return _error(error)
        self._selected_path = None
        return {"ok": True}

    def delete_shortcut(self, shortcut_id):
        """ショートカットを削除する"""
        if not isinstance(shortcut_id, str):
            return False
        return self._save(self._config.delete_shortcut, shortcut_id) is None

    def edit_shortcut(self, shortcut_id, new_name):
        """IDを指定して名前を書き換える"""
        new_name = _clean_name(new_name)
        if not isinstance(shortcut_id, str) or new_name is None:
            return False
        data = self._config.get_all()
        for cat in data["categories"]:
            for item in cat["shortcuts"]:
                if item["id"] == shortcut_id:
                    item["name"] = new_name
                    return self._save(self._config.save, data) is None
        return False

    def edit_category(self, category_id, new_name):
        """カテゴリー名を変更する"""
        new_name = _clean_name(new_name)
        if not isinstance(category_id, str) or new_name is None:
            return False
        data = self._config.get_all()
        for cat in data["categories"]:
            if cat["id"] == category_id:
                cat["name"] = new_name
                return self._save(self._config.save, data) is None
        return False

    def launch_executable(self, shortcut_id):
        """ショートカットIDを受け取り、対応するパスのアプリを起動する"""
        if not isinstance(shortcut_id, str):
            return False
        data = self._config.get_all()
        target_path = None
        for cat in data["categories"]:
            for s in cat["shortcuts"]:
                if s["id"] == shortcut_id:
                    target_path = s["path"]
                    break

        if target_path:
            success = launch_app(target_path)
            return success
        return False

    def select_file(self):
        """ファイル選択ダイアログを開き、選ばれたパスを返す（登録可能なパスとして記録する）"""
        # キャンセル時に前回の選択が残らないよう、先に消しておく
        self._selected_path = None

        window = webview.active_window()
        # フィルタに *.url を追加
        file_types = ('Game files (*.exe;*.lnk;*.url;*.bat)',
                      'All files (*.*)')
        result = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)

        if result and len(result) > 0:
            self._selected_path = _normalize_path(result[0])
            return result[0]  # ここでは解析せず、add_shortcutに渡す
        return None

    def save_order(self, categories_order):
        """
        JS から届いた新しい並び順を保存する。
        並び順に載っていないカテゴリー・ショートカットは消さずに末尾へ残す。
        重複した ID・知らない ID は無視する。形がおかしければ保存しない。
        """
        if not _is_valid_order(categories_order):
            logger.warning("並び順の形が不正なため保存しません: %r", categories_order)
            return False

        data = self._config.get_all()
        categories = {c["id"]: c for c in data["categories"]}
        shortcuts = {}
        home = {}  # ショートカット ID -> 元のカテゴリー ID
        for cat in data["categories"]:
            for s in cat["shortcuts"]:
                shortcuts.setdefault(s["id"], s)
                home.setdefault(s["id"], cat["id"])

        placed_cats, placed_items = set(), set()
        new_shortcuts = {cid: [] for cid in categories}
        cat_order = []
        for order_info in categories_order:
            cat_id = order_info["id"]
            if cat_id not in categories or cat_id in placed_cats:
                continue
            placed_cats.add(cat_id)
            cat_order.append(cat_id)
            for s_id in order_info["shortcuts"]:
                if s_id in shortcuts and s_id not in placed_items:
                    placed_items.add(s_id)
                    new_shortcuts[cat_id].append(shortcuts[s_id])

        # 並び順に無かったものは、元のカテゴリー（の末尾）・元の順番のまま残す
        cat_order += [cid for cid in categories if cid not in placed_cats]
        for cat in data["categories"]:
            for s in cat["shortcuts"]:
                if s["id"] not in placed_items:
                    placed_items.add(s["id"])
                    new_shortcuts[home[s["id"]]].append(s)

        new_categories = []
        for cid in cat_order:
            cat = categories[cid]
            cat["shortcuts"] = new_shortcuts[cid]
            new_categories.append(cat)
        data["categories"] = new_categories
        return self._save(self._config.save, data) is None

    def get_themes(self):
        """themesフォルダ内のCSSファイル名を取得"""
        # API.py から見た相対パスではなく、実行環境に合わせたパス取得が必要
        # main.py で使った get_resource_path をここでも使えるようにするか、
        # sys._MEIPASS を考慮したパス解決を行います。
        if getattr(sys, 'frozen', False):
            # EXE実行時
            base_dir = sys._MEIPASS  # pylint: disable=protected-access
        else:
            # スクリプト実行時（api.py が src/ にあるなら、親の親がルート）
            base_dir = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))

        themes_dir = os.path.join(base_dir, "src", "ui", "themes")

        try:
            if not os.path.exists(themes_dir):
                return ["valorant", "hydrangea_blue"]  # フォールバック

            files = [f.replace(".css", "") for f in os.listdir(
                themes_dir) if f.endswith(".css")]
            return files
        except Exception:  # pylint: disable=broad-exception-caught
            return ["valorant"]
