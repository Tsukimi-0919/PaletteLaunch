import os
import json
import uuid
import shutil


class ConfigManager:
    def __init__(self, config_filename="settings.json"):
        # 1. 実行パスの解決（EXE化しても崩れないように）
        # main.pyがあるディレクトリの1つ上（プロジェクトルート）を基準にする
        base_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        self.config_path = os.path.join(base_dir, config_filename)
        self.example_path = os.path.join(base_dir, "settings.json.example")

        # 2. 初期データの構造（設定とカテゴリーを分離）
        self.default_data = {
            "config": {
                "theme": "valorant",
                "language": "ja"
            },
            "categories": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "General",
                    "shortcuts": []
                }
            ]
        }

        # 3. ファイルの準備（存在しなければexampleからコピー、無ければ作成）
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        """settings.jsonがない場合、exampleからコピーするかデフォルトを作成する"""
        if not os.path.exists(self.config_path):
            if os.path.exists(self.example_path):
                shutil.copy(self.example_path, self.config_path)
            else:
                self.save(self.default_data)

    def _get_raw_data(self):
        """ファイルからデータを読み込む"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return self.default_data

    def save(self, data):
        """データを保存する"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # --- グローバル設定操作 (テーマなど) ---
    def update_setting(self, key, value):
        data = self._get_raw_data()
        data["config"][key] = value
        self.save(data)

    # --- カテゴリー操作 ---
    def add_category(self, name):
        data = self._get_raw_data()
        new_cat = {"id": str(uuid.uuid4()), "name": name, "shortcuts": []}
        data["categories"].append(new_cat)
        self.save(data)
        return new_cat

    def delete_category(self, category_id):
        data = self._get_raw_data()
        data["categories"] = [
            c for c in data["categories"] if c["id"] != category_id]
        self.save(data)

    # --- ショートカット操作 ---
    def add_shortcut(self, category_id, name, path, icon=""):
        data = self._get_raw_data()
        for cat in data["categories"]:
            if cat["id"] == category_id:
                new_item = {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "path": path,
                    "icon": icon
                }
                cat["shortcuts"].append(new_item)
                break
        self.save(data)

    def update_shortcut(self, shortcut_id, name=None, path=None):
        data = self._get_raw_data()
        for cat in data["categories"]:
            for s in cat["shortcuts"]:
                if s["id"] == shortcut_id:
                    if name:
                        s["name"] = name
                    if path:
                        s["path"] = path
                    break
        self.save(data)

    def delete_shortcut(self, shortcut_id):
        data = self._get_raw_data()
        for cat in data["categories"]:
            cat["shortcuts"] = [s for s in cat["shortcuts"]
                                if s["id"] != shortcut_id]
        self.save(data)

    def get_all(self):
        """設定ファイルを読み込む。壊れていたり空ならデフォルトを生成・保存する。"""
        try:
            # 1. あなたのコードでの変数名 self.config_path を使用する
            if not os.path.exists(self.config_path) or os.stat(self.config_path).st_size == 0:
                # 2. メソッドではなく self.default_data を返す
                return self.default_data

            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)

        except (json.JSONDecodeError, IOError, AttributeError) as e:
            print(f"Config load error: {e}. Resetting to default.")
            # 3. エラー時もデフォルトデータを返す
            return self.default_data
