"""settings.json の読み書き。

データを失わないための決まり（docs/backup.md）:
- 書き込みは一時ファイル → flush + fsync → os.replace で差し替える（途中で落ちても元のファイルは残る）。
- 保存の前に、今のファイルが正しければ settings.json.bak（1つ前の保存）と、
  その日のバックアップ settings.YYYYMMDD.bak.json（7日分）を残す。
- 起動時に読めなかったら、壊れたファイルを settings.corrupt-日時.json に退避し、
  .bak から復元する。復元できなければ読み取り専用モードにして、保存をすべて拒否する。
"""
import copy
import datetime
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid

logger = logging.getLogger(__name__)

DAILY_BACKUP_KEEP = 7

DEFAULT_CONFIG = {
    "theme": "valorant",
    "language": "ja",
    "card_size": "medium",
}

# config キーが無い古い形式で、最上位に置かれていた設定
_LEGACY_CONFIG_KEYS = ("theme", "language", "card_size")

# id の無い項目に振る id（同じファイルからは毎回同じ id になるよう、位置から決める）
_ID_NAMESPACE = uuid.UUID("6f1b6c1e-5f43-4b8e-9a52-3c1f0d7e2a90")

# os.replace がウイルス対策ソフト等の一時的なロックで失敗したときの再試行
_REPLACE_RETRIES = 5
_REPLACE_WAIT = 0.1


class SettingsReadOnlyError(Exception):
    """読み取り専用モードで保存しようとした"""


class SchemaError(ValueError):
    """JSON としては読めるが、設定ファイルの形をしていない"""


def _today():
    return datetime.date.today()


def _now():
    return datetime.datetime.now()


def _describe(value):
    """
    ログ用の値の説明（型と長さだけ）。
    保存データ（アイコンの base64 など）をそのままログに出さないため、中身は出さない。
    """
    try:
        return f"{type(value).__name__}(len={len(value)})"
    except TypeError:
        return type(value).__name__


def _fixed_id(*position):
    return str(uuid.uuid5(_ID_NAMESPACE, "/".join(str(p) for p in position)))


def _fix_id(item, seen, *position):
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id or item_id in seen:
        item["id"] = _fixed_id(*position)
        logger.warning("id を補完しました: %s -> %s",
                       item_id if isinstance(item_id, str) and len(item_id) <= 64
                       else _describe(item_id), item["id"])
    seen.add(item["id"])


def _fix_name(item):
    name = item.get("name")
    if not isinstance(name, str):
        item["name"] = "" if name is None else str(name)


def normalize_data(data):
    """
    読み込んだデータの欠けている部分を補い、新しいオブジェクトとして返す。
    すでに入っている値や、知らないキーには触らない。
    最上位が dict でない・categories が list でないときは SchemaError。
    """
    if not isinstance(data, dict):
        raise SchemaError("top level is not an object")
    data = copy.deepcopy(data)

    config = data.get("config")
    if not isinstance(config, dict):
        if "config" in data:
            logger.warning("config が object ではないため初期値にします: %s", _describe(config))
            config = {}
        else:
            # 古い形式: 最上位にあった設定を config に写す
            config = {k: data[k] for k in _LEGACY_CONFIG_KEYS if k in data}
        data["config"] = config
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)

    categories = data.setdefault("categories", [])
    if not isinstance(categories, list):
        raise SchemaError("categories is not a list")

    normalized = []
    seen_ids = set()
    for ci, cat in enumerate(categories):
        if not isinstance(cat, dict):
            logger.warning("カテゴリーではない要素を除外しました: %s", _describe(cat))
            continue
        _fix_id(cat, seen_ids, ci)
        _fix_name(cat)
        shortcuts = cat.get("shortcuts")
        if not isinstance(shortcuts, list):
            if shortcuts is not None:
                logger.warning("shortcuts が list ではないため空にします: %s", _describe(shortcuts))
            shortcuts = []
        fixed = []
        for si, sc in enumerate(shortcuts):
            if not isinstance(sc, dict):
                logger.warning("ショートカットではない要素を除外しました: %s", _describe(sc))
                continue
            _fix_id(sc, seen_ids, ci, si)
            _fix_name(sc)
            if not isinstance(sc.get("path"), str):
                sc["path"] = ""
            if not isinstance(sc.get("icon"), str):
                sc["icon"] = ""
            fixed.append(sc)
        cat["shortcuts"] = fixed
        normalized.append(cat)
    data["categories"] = normalized
    return data


def parse_settings(raw):
    """バイト列を設定データとして読む。読めなければ ValueError（SchemaError を含む）"""
    text = raw.decode("utf-8-sig")  # 手で編集されて BOM が付いていても読む
    return normalize_data(json.loads(text))


def _replace(src, dst):
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_WAIT)


def atomic_write(path, write):
    """同じフォルダの一時ファイルに write(f) で書き、fsync してから path と差し替える"""
    folder, name = os.path.split(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def dump_settings(data):
    """旧バージョンと同じ形式（indent=4, ensure_ascii=False, CRLF, BOM なし）のバイト列にする"""
    text = json.dumps(data, indent=4, ensure_ascii=False)
    return text.replace("\n", "\r\n").encode("utf-8")


class ConfigManager:
    def __init__(self, config_path, example_path=None):
        """config_path, example_path は絶対パスで渡す（main.py で解決する）"""
        if not os.path.isabs(config_path):
            raise ValueError(f"config_path must be absolute: {config_path!r}")
        if example_path is not None and not os.path.isabs(example_path):
            raise ValueError(f"example_path must be absolute: {example_path!r}")

        self.config_path = config_path
        self.example_path = example_path
        folder, filename = os.path.split(config_path)
        self._folder = folder
        self._stem = os.path.splitext(filename)[0]
        self.backup_path = config_path + ".bak"

        self._default_data = {
            "config": dict(DEFAULT_CONFIG),
            "categories": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "General",
                    "shortcuts": []
                }
            ]
        }

        self._read_only = False
        self._read_only_data = None
        self._status = {
            "read_only": False,
            "reason": None,
            "restored_from_backup": False,
            "corrupt_copy": None,
        }
        self._load_on_startup()

    # --- 状態 -----------------------------------------------------------------

    @property
    def default_data(self):
        return copy.deepcopy(self._default_data)

    @property
    def read_only(self):
        return self._read_only

    def get_status(self):
        """起動時の読み込み結果（UI に知らせる用）"""
        return dict(self._status)

    def _enter_read_only(self, reason):
        logger.error("設定ファイルを読み取り専用で開きます（%s）: %s", reason, self.config_path)
        self._read_only = True
        self._read_only_data = self.default_data
        self._status["read_only"] = True
        self._status["reason"] = reason

    # --- 読み込み -------------------------------------------------------------

    def _read_raw(self, path):
        with open(path, "rb") as f:
            return f.read()

    def _load_on_startup(self):
        if not os.path.exists(self.config_path):
            self._create_new()
            return

        try:
            raw = self._read_raw(self.config_path)
        except OSError as e:
            logger.error("設定ファイルを読めません: %s", e)
            self._enter_read_only("unreadable")
            return

        if not raw.decode("utf-8-sig", errors="replace").strip():
            # 空のファイルには守るデータが無い（旧バージョンで書き込み中に落ちた等）
            logger.warning("設定ファイルが空です: %s", self.config_path)
            self._status["reason"] = "empty"
            if not self._restore_from_backup():
                self._create_new()
            return

        try:
            parse_settings(raw)
            return
        except ValueError as e:
            logger.error("設定ファイルが壊れています: %s", e)

        self._status["reason"] = "corrupt"
        self._save_corrupt_copy()
        if not self._restore_from_backup():
            self._enter_read_only("corrupt")

    def _create_new(self):
        """example（無い・壊れていれば初期値）から新しく作る"""
        data = None
        if self.example_path and os.path.exists(self.example_path):
            try:
                data = parse_settings(self._read_raw(self.example_path))
            except (OSError, ValueError) as e:
                logger.warning("settings.json.example を読めません: %s", e)
        if data is None:
            data = self.default_data
        try:
            atomic_write(self.config_path, lambda f: f.write(dump_settings(data)))
        except OSError as e:
            logger.error("設定ファイルを作成できません: %s", e)
            self._enter_read_only("unwritable")

    def _restore_from_backup(self):
        """settings.json.bak が正しければ、その内容で settings.json を作り直す"""
        if not os.path.exists(self.backup_path):
            return False
        try:
            raw = self._read_raw(self.backup_path)
            parse_settings(raw)
        except (OSError, ValueError) as e:
            logger.error("バックアップも読めません: %s", e)
            return False
        try:
            atomic_write(self.config_path, lambda f: f.write(raw))
        except OSError as e:
            logger.error("バックアップから復元できません: %s", e)
            return False
        logger.warning("settings.json.bak から復元しました")
        self._status["restored_from_backup"] = True
        return True

    def _save_corrupt_copy(self):
        stamp = _now().strftime("%Y%m%d-%H%M%S")
        for n in range(100):
            suffix = "" if n == 0 else f"-{n}"
            path = os.path.join(self._folder, f"{self._stem}.corrupt-{stamp}{suffix}.json")
            if not os.path.exists(path):
                break
        try:
            shutil.copy2(self.config_path, path)
        except OSError as e:
            logger.error("壊れた設定ファイルを退避できません: %s", e)
            return
        logger.warning("壊れた設定ファイルを退避しました: %s", path)
        self._status["corrupt_copy"] = os.path.basename(path)

    def _get_raw_data(self):
        """ファイルからデータを読み込む（読めなければ読み取り専用モードにする）"""
        if self._read_only:
            return copy.deepcopy(self._read_only_data)
        try:
            return parse_settings(self._read_raw(self.config_path))
        except (OSError, ValueError) as e:
            # 起動後に読めなくなった場合は復元を試みず、保存を止めて上書きを防ぐ
            logger.error("設定ファイルを読み直せません: %s", e)
            if isinstance(e, ValueError):
                self._save_corrupt_copy()
                self._enter_read_only("corrupt")
            else:
                self._enter_read_only("unreadable")
            return copy.deepcopy(self._read_only_data)

    def get_all(self):
        """設定を読み込む（返すのは毎回新しいオブジェクト）"""
        return self._get_raw_data()

    # --- 保存 -----------------------------------------------------------------

    def save(self, data):
        """
        データを保存する。読み取り専用なら SettingsReadOnlyError、
        書き込みに失敗したら OSError（どちらの場合も元のファイルは変わらない）。
        """
        if self._read_only:
            raise SettingsReadOnlyError(self.config_path)
        payload = dump_settings(normalize_data(data))
        self._backup_current()
        atomic_write(self.config_path, lambda f: f.write(payload))

    def _backup_current(self):
        """今のファイルが正しければ .bak と日ごとのバックアップを残す（失敗しても保存は続ける）"""
        try:
            raw = self._read_raw(self.config_path)
            parse_settings(raw)
        except (OSError, ValueError) as e:
            logger.warning("保存前のファイルが読めないため、バックアップを作りません: %s", e)
            return

        try:
            atomic_write(self.backup_path, lambda f: f.write(raw))
        except OSError as e:
            logger.warning("settings.json.bak を作成できません: %s", e)

        try:
            self._make_daily_backup(raw)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("日ごとのバックアップを作成できません: %s", e)

    def daily_backup_path(self, day):
        return os.path.join(self._folder, f"{self._stem}.{day:%Y%m%d}.bak.json")

    def list_daily_backups(self):
        """日ごとのバックアップのパスを新しい順に返す"""
        pattern = re.compile(rf"^{re.escape(self._stem)}\.(\d{{8}})\.bak\.json$")
        found = []
        for name in os.listdir(self._folder):
            m = pattern.match(name)
            if m:
                found.append((m.group(1), os.path.join(self._folder, name)))
        return [path for _, path in sorted(found, reverse=True)]

    def _make_daily_backup(self, raw):
        path = self.daily_backup_path(_today())
        if os.path.exists(path):
            return
        atomic_write(path, lambda f: f.write(raw))
        logger.info("日ごとのバックアップを作成しました: %s", path)
        for old in self.list_daily_backups()[DAILY_BACKUP_KEEP:]:
            try:
                os.remove(old)
                logger.info("古いバックアップを削除しました: %s", old)
            except OSError as e:
                logger.warning("古いバックアップを削除できません: %s", e)

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
    def add_shortcut(self, category_id, name, path, icon="", target=None):
        """path には登録したファイルのパスをそのまま、target には表示用の解決先を保存する"""
        data = self._get_raw_data()
        for cat in data["categories"]:
            if cat["id"] == category_id:
                new_item = {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "path": path,
                    "icon": icon
                }
                if target:
                    new_item["target"] = target
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
