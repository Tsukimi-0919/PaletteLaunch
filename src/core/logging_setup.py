"""
ログの設定。%LOCALAPPDATA%\\PaletteLaunch\\logs\\palettelaunch.log に出力する（ローテーションあり）。

注意: ログにアイコンの base64 や設定ファイルの中身全体を出さないこと。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FILE_NAME = "palettelaunch.log"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def default_log_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PaletteLaunch", "logs")


def setup_logging(log_dir=None, console=None):
    """
    ルートロガーにファイル（とスクリプト実行時はコンソール）を設定する。
    ログファイルのパスを返す。ファイルを作れなければ None（アプリは止めない）。
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT)
    if console is None:
        console = not getattr(sys, "frozen", False)

    log_path = None
    try:
        log_dir = log_dir or default_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, LOG_FILE_NAME)
        handler = RotatingFileHandler(
            log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError as e:
        log_path = None
        if sys.stderr:  # EXE（console=False）では None
            sys.stderr.write(f"ログファイルを作れません: {e}\n")

    if console and sys.stderr:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)
    return log_path
