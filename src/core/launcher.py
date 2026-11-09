"""
ショートカットの起動と、表示用の解決処理を行うモジュール。
"""
import configparser
import logging
import os
import subprocess
from urllib.parse import urlsplit

import win32com.client

logger = logging.getLogger(__name__)

# OS の関連付けで開いてよい URL スキーム
ALLOWED_SCHEMES = frozenset(
    {"steam", "riot", "https", "http", "com.epicgames.launcher"})

# 要求された操作には管理者特権が必要です
_ERROR_ELEVATION_REQUIRED = 740


def _get_scheme(value):
    """URL のスキームを小文字で返す。URL でなければ None（ドライブ文字は除外）"""
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return None
    # "C:\\..." は scheme="c" になるため、1文字のスキームはパスとみなす
    if len(scheme) <= 1:
        return None
    return scheme


def is_allowed_url(value):
    """許可リストにあるスキームの URL かどうか"""
    return _get_scheme(value) in ALLOWED_SCHEMES


def read_url_file(path):
    """
    .url ファイルを読み込み ConfigParser を返す。読めなければ None。
    % 展開は行わず、UTF-8（BOM 可）で失敗したら cp932 で再試行する。
    """
    for encoding in ("utf-8-sig", "cp932"):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            with open(path, "r", encoding=encoding) as f:
                parser.read_file(f)
            return parser
        except UnicodeDecodeError:
            continue
        except (OSError, configparser.Error) as e:
            logger.warning(".url の読み込みに失敗: %s (%s)", path, e)
            return None
    logger.warning(".url の文字コードを判別できません: %s", path)
    return None


def _read_url_target(path):
    """.url ファイルから URL を取り出す。無ければ None"""
    parser = read_url_file(path)
    if parser is None:
        return None
    return parser.get("InternetShortcut", "URL", fallback=None)


def launch_app(path):
    """
    登録されたパス（ファイルまたは URL）を起動する。成功したら True。
    """
    try:
        if not path:
            logger.warning("起動を拒否: パスが空です")
            return False

        # 1. URL スキーム（旧形式の保存データを含む）
        scheme = _get_scheme(path)
        if scheme is not None:
            if scheme not in ALLOWED_SCHEMES:
                logger.warning("起動を拒否: 許可されていないスキーム %r: %s",
                               scheme, path)
                return False
            os.startfile(path)
            return True

        # 2. ファイルの存在チェック
        if not os.path.isfile(path):
            logger.warning("起動を拒否: ファイルが存在しません: %s", path)
            return False

        ext = os.path.splitext(path)[1].lower()
        cwd = os.path.dirname(path) or None

        # 3. .url は中身の URL を検証してから開く
        if ext == ".url":
            url = _read_url_target(path)
            if not url:
                logger.warning("起動を拒否: .url から URL を読めません: %s", path)
                return False
            if not is_allowed_url(url):
                logger.warning("起動を拒否: .url の URL が許可されていません %r: %s",
                               url, path)
                return False
            os.startfile(path)
            return True

        # 4. .lnk はショートカット側の引数・作業フォルダに任せる
        if ext == ".lnk":
            os.startfile(path)
            return True

        # 5. .bat は自身のフォルダを作業フォルダにする
        if ext == ".bat":
            os.startfile(path, cwd=cwd)
            return True

        # 6. .exe は引数をリストで渡す（引用符なしパス問題の回避）
        if ext == ".exe":
            try:
                subprocess.Popen([path], cwd=cwd)
            except OSError as e:
                if getattr(e, "winerror", None) != _ERROR_ELEVATION_REQUIRED:
                    raise
                # 管理者権限が必要な exe は ShellExecute 経由で UAC を出す
                logger.info("管理者権限が必要なため startfile で起動: %s", path)
                os.startfile(path, cwd=cwd)
            return True

        logger.warning("起動を拒否: 許可されていない拡張子 %r: %s", ext, path)
        return False

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("起動失敗: %s (%s)", path, e)
        return False


def resolve_shortcut(path):
    """
    .lnk / .url の解決先を返す（表示・アイコン取得用。起動には使わない）。
    """
    ext = path.lower()

    # 1. 通常のショートカット (.lnk)
    if ext.endswith('.lnk'):
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(path)
            return shortcut.TargetPath if shortcut.TargetPath else path
        except Exception:  # pylint: disable=broad-exception-caught
            return path

    # 2. インターネットショートカット (.url) - Valorant/Apex等
    if ext.endswith('.url'):
        return _read_url_target(path) or path

    return path
