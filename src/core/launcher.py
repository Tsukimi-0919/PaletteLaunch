"""
ショートカットの起動と、表示用の解決処理を行うモジュール。
"""
import configparser
import logging
import os
import re
import subprocess
from urllib.parse import urlsplit

import pythoncom
import win32com.client

logger = logging.getLogger(__name__)

# ドライブ文字付きの絶対パス（C:\... / C:/...）
_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")

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


def is_unc_path(path):
    r"""UNC パス（\\server\share, //server/share, \\?\...）かどうか"""
    return isinstance(path, str) and path.startswith(("\\\\", "//"))


def is_missing_drive_target(target):
    """
    .lnk の解決先が「ドライブ文字付きの絶対パスで、存在しない」かどうか。
    空・シェルフォルダ・相対パス・UNC は判定対象外（False）。
    """
    if not target or not _DRIVE_ABS_RE.match(target):
        return False
    return not os.path.exists(target)


def get_lnk_info(path):
    """
    .lnk の TargetPath と IconLocation を返す: {"target": str, "icon_location": str}
    読めなければ None。pywebview の API スレッドから呼ばれるため COM を初期化する。
    """
    pythoncom.CoInitialize()
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(path)
        return {
            "target": shortcut.TargetPath or "",
            "icon_location": shortcut.IconLocation or "",
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(".lnk の読み込みに失敗: %s (%s)", path, e)
        return None
    finally:
        pythoncom.CoUninitialize()


def parse_icon_location(value):
    """
    "path,index" 形式を (path, index) に分解する。環境変数は展開する。
    パスが空なら None。
    """
    if not value:
        return None
    icon_path, sep, index_str = value.rpartition(",")
    if not sep:
        icon_path, index_str = value, "0"
    icon_path = os.path.expandvars(icon_path.strip().strip('"'))
    if not icon_path:
        return None
    try:
        index = int(index_str.strip())
    except ValueError:
        index = 0
    return icon_path, index


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


def read_url_target(path):
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
            url = read_url_target(path)
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
        #    リンク先が見つからない場合は Windows の「ショートカットの検索」を出さない
        if ext == ".lnk":
            info = get_lnk_info(path)
            if info and is_missing_drive_target(info["target"]):
                logger.warning("起動を拒否: .lnk のリンク先が存在しません '%s': %s",
                               info["target"], path)
                return False
            os.startfile(path)
            return True

        # 5. .bat は自身のフォルダを作業フォルダにする
        if ext == ".bat":
            os.startfile(path, cwd=cwd)
            return True

        # 6. .exe は引数をリストで渡す（引用符なしパス問題の回避）
        #    コンソールアプリが親のコンソールを使わないよう新しいコンソールを割り当てる
        if ext == ".exe":
            try:
                subprocess.Popen([path], cwd=cwd,
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
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
        info = get_lnk_info(path)
        return (info and info["target"]) or path

    # 2. インターネットショートカット (.url) - Valorant/Apex等
    if ext.endswith('.url'):
        return read_url_target(path) or path

    return path
