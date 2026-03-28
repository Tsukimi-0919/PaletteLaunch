"""
UIからのリクエストを受け取り、設定管理やアプリ起動を制御するAPIモジュール。
"""
import configparser
import os
import uuid
import webview
import json
import sys

from src.core.config import ConfigManager
from src.core.launcher import launch_app
from src.core.icons import get_icon_base64
from src.core.launcher import launch_app, resolve_shortcut


class API:
    """
    フロントエンド(JavaScript)とバックエンド(Python)を仲介するクラス。
    """

    def __init__(self, settings_path):
        self.settings_path = settings_path
        self.load_settings()
        # 設定ファイルの管理クラスをインスタンス化
        self.config = ConfigManager(self.settings_path)

    def update_setting(self, key, value):
        """テーマと言語設定を更新して保存する"""
        try:
            self.config.update_setting(key, value)
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"設定更新エラー: {e}")
            return False

    def load_settings(self):
        # 今まで 'settings.json' と直接書いていた部分を self.settings_path に変える
        if os.path.exists(self.settings_path):
            with open(self.settings_path, 'r', encoding='utf-8') as f:
                self.settings = json.load(f)
        else:
            self.settings = {"theme": "default", "categories": []}

    def save_settings(self):
        with open(self.settings_path, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=4, ensure_ascii=False)

    def get_config(self):
        """現在の全設定をUIに返す"""
        return self.config.get_all()

    def add_category(self, name):
        """新しいカテゴリーを追加する"""
        data = self.config.get_all()

        new_cat = {
            "id": str(uuid.uuid4()),
            "name": name,
            "shortcuts": []
        }
        data["categories"].append(new_cat)

        self.config.save(data)
        return True

    def delete_category(self, category_id):
        """カテゴリーを削除する"""
        data = self.config.get_all()
        data["categories"] = [
            c for c in data["categories"] if c["id"] != category_id]
        self.config.save(data)
        return True

    def add_shortcut(self, category_id, name, path):
        """ショートカットを追加"""
        real_path = resolve_shortcut(path)
        icon_data = ""

        # --- Steam (.url) の場合のアイコン取得強化 ---
        if path.lower().endswith('.url'):
            try:
                config = configparser.ConfigParser()
                config.read(path, encoding='utf-8')  # 念のためエンコード指定
                if config.has_option('InternetShortcut', 'IconFile'):
                    icon_path = config.get('InternetShortcut', 'IconFile')
                    # 「,0」などのインデックス指定を削除して純粋なパスにする
                    icon_path = icon_path.split(',')[0].strip()
                    # IconFileにパスがあればそこから優先的に取る
                    icon_data = get_icon_base64(icon_path)
            except Exception as e:
                print(f"URLアイコン詳細解析失敗: {e}")

        # --- 通常のアイコン取得（上記で取れなかった場合） ---
        if not icon_data:
            icon_data = get_icon_base64(real_path)

        # --- それでもダメなら元のファイルから ---
        if not icon_data:
            icon_data = get_icon_base64(path)

        self.config.add_shortcut(category_id, name, real_path, icon=icon_data)
        return True

    def delete_shortcut(self, shortcut_id):
        """ショートカットを削除する"""
        self.config.delete_shortcut(shortcut_id)
        return True

    def edit_shortcut(self, shortcut_id, new_name):
        """IDを指定して名前を書き換える"""
        data = self.config.get_all()
        for cat in data["categories"]:
            for item in cat["shortcuts"]:
                if item["id"] == shortcut_id:
                    item["name"] = new_name
                    self.config.save(data)
                    return True
        return False

    def edit_category(self, category_id, new_name):
        """カテゴリー名を変更する"""
        data = self.config.get_all()
        for cat in data["categories"]:
            if cat["id"] == category_id:
                cat["name"] = new_name
                self.config.save(data)
                return True
        return False

    def launch_executable(self, shortcut_id):
        """ショートカットIDを受け取り、対応するパスのアプリを起動する"""
        data = self.config.get_all()
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
        window = webview.active_window()
        # フィルタに *.url を追加
        file_types = ('Game files (*.exe;*.lnk;*.url;*.bat)',
                      'All files (*.*)')
        result = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)

        if result and len(result) > 0:
            return result[0]  # ここでは解析せず、add_shortcutに渡す
        return None

    def save_order(self, categories_order):
        """JSから届いた新しい並び順を保存する"""
        data = self.config.get_all()

        # 全ショートカットを一時的に回収
        all_shortcuts = []
        for cat in data["categories"]:
            all_shortcuts.extend(cat["shortcuts"])
            cat["shortcuts"] = []

        # 新しい順番に基づいて再構成
        new_categories = []
        for order_info in categories_order:
            cat = next((c for c in data["categories"]
                       if c["id"] == order_info["id"]), None)
            if cat:
                for s_id in order_info["shortcuts"]:
                    s = next(
                        (item for item in all_shortcuts if item["id"] == s_id), None)
                    if s:
                        cat["shortcuts"].append(s)
                new_categories.append(cat)

        data["categories"] = new_categories
        self.config.save(data)
        return True

    def get_themes(self):
        """themesフォルダ内のCSSファイル名を取得"""
        # API.py から見た相対パスではなく、実行環境に合わせたパス取得が必要
        # main.py で使った get_resource_path をここでも使えるようにするか、
        # sys._MEIPASS を考慮したパス解決を行います。
        if getattr(sys, 'frozen', False):
            # EXE実行時
            base_dir = sys._MEIPASS
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
        except Exception:
            return ["valorant"]
