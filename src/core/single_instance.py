"""
アプリの二重起動防止（名前付きミューテックス）と、起動済みウィンドウの前面表示。

ウィンドウはタイトルだけで探さない（エクスプローラーの「PaletteLaunch」フォルダの
ウィンドウなどを誤って前面に出さないため）。見つけたウィンドウのプロセスの実行ファイルが
自分と同じ（EXE なら PaletteLaunch.exe、開発時は python）ときだけ前面に出す。
確認できなければ何もしない。
"""
import ctypes
import getpass
import logging
import os
import re
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

WINDOW_TITLE = "PaletteLaunch"
_MUTEX_PREFIX = "Local\\PaletteLaunch.SingleInstance."
_ERROR_ALREADY_EXISTS = 183
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SW_RESTORE = 9


def _current_user_id():
    """ユーザーを区別する文字列（SID。取れなければユーザー名）"""
    try:
        # pylint: disable=import-outside-toplevel
        import win32api
        import win32security
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("SID を取得できないため、ユーザー名でミューテックス名を作ります")
        try:
            return getpass.getuser()
        except Exception:  # pylint: disable=broad-exception-caught
            return "unknown"


def mutex_name(user_id=None):
    """Local\\ で始まる、ユーザーごとのミューテックス名"""
    user_id = _current_user_id() if user_id is None else user_id
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id)) or "unknown"
    return _MUTEX_PREFIX + safe


def acquire(name=None):
    """
    ミューテックスを作る。最初のインスタンスならハンドル（終了まで保持する）を返す。
    すでに起動済みなら None。ミューテックスを作れないときは起動を止めない（"" を返す）。
    """
    try:
        import win32api  # pylint: disable=import-outside-toplevel
        import win32event  # pylint: disable=import-outside-toplevel
        handle = win32event.CreateMutex(None, False, name or mutex_name())
        if win32api.GetLastError() == _ERROR_ALREADY_EXISTS:
            win32api.CloseHandle(handle)
            return None
        return handle
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("ミューテックスを作れません（二重起動の防止なしで続けます）")
        return ""


def expected_executables():
    """起動済みの PaletteLaunch のプロセスとして認める実行ファイル（正規化済み）"""
    paths = {sys.executable}
    if not getattr(sys, "frozen", False):
        # venv の Scripts\python.exe は元の python.exe を子プロセスとして起動するため、両方を認める
        base = getattr(sys, "_base_executable", None)
        if base:
            paths.add(base)
    return {os.path.normcase(os.path.realpath(p)) for p in paths if p}


def _process_image_path(pid):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def _find_windows(title):
    """タイトルが一致するトップレベルウィンドウの (hwnd, pid) 一覧"""
    import win32gui  # pylint: disable=import-outside-toplevel
    import win32process  # pylint: disable=import-outside-toplevel
    found = []

    def callback(hwnd, _):
        if win32gui.GetWindowText(hwnd) == title:
            found.append((hwnd, win32process.GetWindowThreadProcessId(hwnd)[1]))
        return True

    win32gui.EnumWindows(callback, None)
    return found


def activate_existing(title=WINDOW_TITLE, find_windows=None, image_path=None, allowed=None):
    """
    起動済みの PaletteLaunch のウィンドウを前面に出す。出せたら True。
    プロセスの実行ファイルを確認できたウィンドウ以外には何もしない。
    find_windows / image_path / allowed はテスト用。
    """
    try:
        find_windows = find_windows or _find_windows
        image_path = image_path or _process_image_path
        allowed = expected_executables() if allowed is None else allowed
        for hwnd, pid in find_windows(title):
            path = image_path(pid)
            if not path or os.path.normcase(os.path.realpath(path)) not in allowed:
                continue
            import win32gui  # pylint: disable=import-outside-toplevel
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, _SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:  # pylint: disable=broad-exception-caught
                # フォアグラウンドではないプロセスからは前面に出せない（Windows の制限）。
                # 代わりにタスクバーのボタンを点滅させて知らせる
                logger.info("起動済みのウィンドウを前面に出せないため、点滅させます")
                win32gui.FlashWindow(hwnd, True)
            return True
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("起動済みのウィンドウを前面に出せません")
        return False
    logger.info("起動済みの PaletteLaunch のウィンドウを確認できませんでした")
    return False
