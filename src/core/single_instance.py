"""
アプリの二重起動防止（名前付きミューテックス）と、起動済みウィンドウの前面表示。

■ 流れ
  1つ目のインスタンス:
    - ミューテックスを取る（acquire）。
    - ウィンドウが表示されたら、自分の PID とウィンドウハンドルを
      %LOCALAPPDATA%\\PaletteLaunch\\instance.json に記録する（InstanceHost.publish）。
    - 名前付きイベント（前面化の依頼）を待つスレッドを動かし、依頼が来たら自分で前面に出る。
  2つ目のインスタンス（activate_existing）:
    - 記録を読み、そのウィンドウが本当にその PID のもので、タイトルが一致するか確かめる。
    - AllowSetForegroundWindow(PID) で1つ目に前面化の権限を渡し、名前付きイベントで依頼する。
    - 前面に出なければ自分でも SetForegroundWindow を試し、だめならタスクバーで点滅させる。
    - どの段階の結果も必ずログに出す。

■ 実行ファイル名で見分けない理由
  開発時の .venv\\Scripts\\python.exe は、本物の python.exe を子プロセスとして起動する
  ランチャーで、ウィンドウを持つプロセスの実行ファイル名が sys.executable と一致しない
  （2026-11-10 に確認）。そのため PID の記録で見分ける。

■ 前面化の制限（Windows）
  SetForegroundWindow は「フォアグラウンドのプロセス、またはそれが起動したプロセス」
  などにしか許されない。エクスプローラーから起動した EXE は許されるが、.venv の
  ランチャーの子プロセスは許されないことがある。その場合は点滅で知らせる。
"""
import ctypes
import getpass
import json
import logging
import os
import re
import threading
import time
from ctypes import wintypes

logger = logging.getLogger(__name__)

WINDOW_TITLE = "PaletteLaunch"
_MUTEX_PREFIX = "Local\\PaletteLaunch.SingleInstance."
_EVENT_PREFIX = "Local\\PaletteLaunch.Activate."
INSTANCE_FILE_NAME = "instance.json"

_ERROR_ALREADY_EXISTS = 183
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_FLASHW_ALL = 0x3
_FLASHW_TIMERNOFG = 0xC

# 2つ目が記録を待つ時間（1つ目がまだ起動中のとき用）
RECORD_WAIT_SECONDS = 5.0
# 1つ目が前面に出るのを待つ時間
ACTIVATE_WAIT_SECONDS = 1.5


# --- Win32 呼び出し（テストでは差し替える） -------------------------------------

class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", wintypes.RECT)]


_WPF_RESTORETOMAXIMIZED = 0x2


class _FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]


class Win32:
    """必要な Win32 API だけを ctypes で呼ぶ薄い層"""

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u, k = self.user32, self.kernel32
        u.IsWindow.argtypes = [wintypes.HWND]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsZoomed.argtypes = [wintypes.HWND]
        u.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(_WINDOWPLACEMENT)]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        u.FlashWindowEx.argtypes = [ctypes.POINTER(_FLASHWINFO)]
        u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                                  wintypes.LPARAM]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        k.CreateEventW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.OpenEventW.restype = wintypes.HANDLE
        k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k.SetEvent.argtypes = [wintypes.HANDLE]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    def last_error(self):
        return ctypes.get_last_error()

    def is_window(self, hwnd):
        return bool(self.user32.IsWindow(hwnd))

    def window_pid(self, hwnd):
        pid = wintypes.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def window_text(self, hwnd):
        buf = ctypes.create_unicode_buffer(512)
        self.user32.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value

    def find_windows(self, pid, title):
        """pid のプロセスが持つ、タイトルが title の表示中のトップレベルウィンドウ"""
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _):
            if self.window_pid(hwnd) == pid and self.user32.IsWindowVisible(hwnd) \
                    and self.window_text(hwnd) == title:
                found.append(int(hwnd))
            return True

        self.user32.EnumWindows(callback, 0)
        return found

    def is_iconic(self, hwnd):
        return bool(self.user32.IsIconic(hwnd))

    def is_zoomed(self, hwnd):
        return bool(self.user32.IsZoomed(hwnd))

    def restores_to_maximized(self, hwnd):
        """最小化しているウィンドウが、復元すると最大化に戻るか（最大化から最小化した）"""
        placement = _WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(_WINDOWPLACEMENT)
        if not self.user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            return False
        return bool(placement.flags & _WPF_RESTORETOMAXIMIZED)

    def set_foreground(self, hwnd):
        ok = bool(self.user32.SetForegroundWindow(hwnd))
        return ok, (0 if ok else self.last_error())

    def foreground_window(self):
        return int(self.user32.GetForegroundWindow() or 0)

    def allow_set_foreground(self, pid):
        ok = bool(self.user32.AllowSetForegroundWindow(pid))
        return ok, (0 if ok else self.last_error())

    def flash(self, hwnd):
        info = _FLASHWINFO(ctypes.sizeof(_FLASHWINFO), hwnd, _FLASHW_ALL | _FLASHW_TIMERNOFG, 0, 0)
        self.user32.FlashWindowEx(ctypes.byref(info))

    def create_event(self, name):
        return self.kernel32.CreateEventW(None, False, False, name)

    def open_event(self, name):
        handle = self.kernel32.OpenEventW(_EVENT_MODIFY_STATE | _SYNCHRONIZE, False, name)
        return handle, (0 if handle else self.last_error())

    def set_event(self, handle):
        return bool(self.kernel32.SetEvent(handle))

    def wait(self, handle, timeout_ms):
        return self.kernel32.WaitForSingleObject(handle, timeout_ms) == _WAIT_OBJECT_0

    def close(self, handle):
        if handle:
            self.kernel32.CloseHandle(handle)


# --- pywebview の API での復元・前面化 ---------------------------------------------

def activate_window_via_pywebview(window, win32, hwnd, settle=0.3):
    """
    1つ目のインスタンスが、自分のウィンドウを復元して前面に出す。
    状態の変更は pywebview の API（UI スレッドで WinForms の WindowState / Show / Activate を
    変える）だけで行う。
    UI スレッド以外（この待ち受けスレッドなど）から Win32 の ShowWindow で最小化から復元すると、
    WinForms の WindowState とコントロールの大きさは正しく戻るのに、WebView2 の中身が描画されず
    背景色だけの空のウィンドウになる（2026-11-10 に確認。同じ ShowWindow でも UI スレッドで
    呼べば描画される）。WebView2 のコントローラーは UI スレッドで操作する前提のため。
    Win32 は状態を調べる（IsIconic など）ためだけに使う。
    戻り値: (前面に出せたか, 使った方法)
    """
    def restore_from_minimized():
        if win32.restores_to_maximized(hwnd):
            window.maximize()   # 最大化から最小化したウィンドウは最大化に戻す
        else:
            window.restore()

    if win32.is_iconic(hwnd):
        restore_from_minimized()
    window.show()  # Show() + Activate()（前面化の権限があれば前面に出る）
    time.sleep(settle)
    if win32.foreground_window() == hwnd:
        return True, "show"

    # 前面化の権限が無いと Activate は効かない。最小化 → 復元はウィンドウを有効にするので、
    # それを pywebview の API で行う（最大化していたら最大化に戻す）。
    zoomed = win32.is_zoomed(hwnd)
    window.minimize()
    time.sleep(settle)
    if zoomed:
        window.maximize()
    else:
        window.restore()
    window.show()
    time.sleep(settle)
    return win32.foreground_window() == hwnd, "minimize-restore"


# --- 名前 ---------------------------------------------------------------------

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


def _safe_user_id(user_id=None):
    user_id = _current_user_id() if user_id is None else user_id
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id)) or "unknown"


def mutex_name(user_id=None):
    """Local\\ で始まる、ユーザーごとのミューテックス名"""
    return _MUTEX_PREFIX + _safe_user_id(user_id)


def activate_event_name(user_id=None):
    """Local\\ で始まる、ユーザーごとの「前面化の依頼」イベント名"""
    return _EVENT_PREFIX + _safe_user_id(user_id)


def default_instance_file():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PaletteLaunch", INSTANCE_FILE_NAME)


# --- ミューテックス -----------------------------------------------------------

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


# --- 記録ファイル ---------------------------------------------------------------

def write_record(path, pid, hwnd):
    """PID とウィンドウハンドルを記録する（同じフォルダの一時ファイル → 差し替え）"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{pid}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"pid": int(pid), "hwnd": int(hwnd), "title": WINDOW_TITLE}, f)
    os.replace(tmp, path)


def read_record(path):
    """記録を読む。{"pid": int, "hwnd": int} か None"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning("[instance] 記録を読めません: %s (%s)", path, e)
        return None
    pid, hwnd = (data.get("pid"), data.get("hwnd")) if isinstance(data, dict) else (None, None)
    if not (isinstance(pid, int) and pid > 0 and isinstance(hwnd, int) and hwnd > 0) \
            or isinstance(pid, bool) or isinstance(hwnd, bool):
        logger.warning("[instance] 記録の形が不正です: %s", path)
        return None
    return {"pid": pid, "hwnd": hwnd}


def remove_record(path, pid):
    """自分（pid）の記録なら消す"""
    record = read_record(path)
    if record and record["pid"] == pid:
        try:
            os.remove(path)
        except OSError as e:
            logger.warning("[instance] 記録を消せません: %s", e)


# --- 1つ目のインスタンス側 -------------------------------------------------------

class InstanceHost:
    """1つ目のインスタンス: 記録の作成と、前面化の依頼の待ち受け"""

    def __init__(self, window=None, path=None, win32=None, pid=None, event_name=None):
        self._window = window   # pywebview のウィンドウ（復元・前面化に使う）
        self._path = path or default_instance_file()
        self._win32 = win32 or Win32()
        self._pid = pid or os.getpid()
        self._event_name = event_name or activate_event_name()
        self._event = None
        self._hwnd = None
        self._stop = threading.Event()
        self._thread = None

    def publish(self, attempts=20, interval=0.1):
        """自分のウィンドウを探して記録し、依頼の待ち受けを始める。成功したら True"""
        hwnds = []
        for _ in range(attempts):
            hwnds = self._win32.find_windows(self._pid, WINDOW_TITLE)
            if hwnds:
                break
            time.sleep(interval)
        if not hwnds:
            logger.warning("[instance] 自分のウィンドウが見つからないため、記録を作りません（PID %d）",
                           self._pid)
            return False
        self._hwnd = hwnds[0]
        try:
            write_record(self._path, self._pid, self._hwnd)
        except OSError as e:
            logger.warning("[instance] 記録を作れません: %s (%s)", self._path, e)
            return False

        self._event = self._win32.create_event(self._event_name)
        if not self._event:
            logger.warning("[instance] 前面化の依頼のイベントを作れません（エラー %d）",
                           self._win32.last_error())
        else:
            self._thread = threading.Thread(target=self._listen, name="instance-activate",
                                            daemon=True)
            self._thread.start()
        logger.info("[instance] 記録しました: PID %d、ウィンドウ %#x（%s）",
                    self._pid, self._hwnd, self._path)
        return True

    def _listen(self):
        while not self._stop.is_set():
            if self._win32.wait(self._event, 500):
                if self._stop.is_set():
                    break
                self.bring_to_front()

    def bring_to_front(self):
        """依頼を受けて自分のウィンドウを前面に出す（2つ目から権限を渡されている前提）"""
        logger.info("[instance] 前面化の依頼を受けました（最小化 %s、最大化 %s）",
                    self._win32.is_iconic(self._hwnd), self._win32.is_zoomed(self._hwnd))
        if self._window is None:
            logger.warning("[instance] pywebview のウィンドウが無いため、前面に出せません")
            return False
        ok, method = activate_window_via_pywebview(self._window, self._win32, self._hwnd)
        if ok:
            logger.info("[instance] 前面に出しました（%s）", method)
        else:
            logger.warning("[instance] 前面に出せません（%s を試しました）", method)
        return ok

    def close(self):
        self._stop.set()
        if self._event:
            self._win32.set_event(self._event)  # 待ち受けを止める
        if self._thread:
            self._thread.join(timeout=2)
        self._win32.close(self._event)
        self._event = None
        remove_record(self._path, self._pid)


# --- 2つ目のインスタンス側 -------------------------------------------------------

def activate_existing(path=None, win32=None, event_name=None,
                      record_wait=RECORD_WAIT_SECONDS, activate_wait=ACTIVATE_WAIT_SECONDS):
    """
    起動済みの PaletteLaunch のウィンドウを前面に出す。前面に出せたら True。
    記録のウィンドウが記録の PID のもので、タイトルが一致するときだけ操作する。
    結果は必ずログに出す。
    """
    path = path or default_instance_file()
    try:
        win32 = win32 or Win32()
        event_name = event_name or activate_event_name()

        # 1. 記録を読む（1つ目がまだ起動中なら、記録ができるまで待つ）
        deadline = time.monotonic() + record_wait
        record = read_record(path)
        while record is None and time.monotonic() < deadline:
            time.sleep(0.2)
            record = read_record(path)
        if record is None:
            logger.warning("[instance] 起動済みのインスタンスの記録が見つかりません（%s）", path)
            return False
        pid, hwnd = record["pid"], record["hwnd"]
        logger.info("[instance] 記録を読みました: PID %d、ウィンドウ %#x", pid, hwnd)

        # 2. そのウィンドウが本当にその PID のものか確かめる
        if not win32.is_window(hwnd):
            logger.warning("[instance] 記録のウィンドウ %#x がありません（古い記録）", hwnd)
            return False
        owner = win32.window_pid(hwnd)
        if owner != pid:
            logger.warning("[instance] ウィンドウ %#x の PID が一致しません（記録 %d、実際 %d）",
                           hwnd, pid, owner)
            return False
        title = win32.window_text(hwnd)
        if title != WINDOW_TITLE:
            logger.warning("[instance] ウィンドウ %#x のタイトルが一致しません: %r", hwnd, title)
            return False
        logger.info("[instance] ウィンドウを確認しました（PID 一致）")

        # 3. 1つ目に前面化の権限を渡し、依頼する
        ok, error = win32.allow_set_foreground(pid)
        if ok:
            logger.info("[instance] AllowSetForegroundWindow(%d) に成功しました", pid)
        else:
            logger.warning("[instance] AllowSetForegroundWindow(%d) に失敗しました（エラー %d）。"
                           "このプロセスに前面化の権限がない可能性があります", pid, error)
        event, error = win32.open_event(event_name)
        if event:
            win32.set_event(event)
            win32.close(event)
            logger.info("[instance] 起動済みのインスタンスに前面化を依頼しました")
        else:
            logger.warning("[instance] 前面化の依頼のイベントを開けません（エラー %d）", error)

        # 4. 前面に出たか確かめる。出なければ自分でも試し、だめなら点滅させる
        deadline = time.monotonic() + activate_wait
        while time.monotonic() < deadline:
            if win32.foreground_window() == hwnd:
                logger.info("[instance] 起動済みのウィンドウが前面に出ました")
                return True
            time.sleep(0.1)
        # 2つ目から ShowWindow で復元すると、1つ目の WebView2 が描画されなくなるので、
        # ここでは状態を変えずに前面化だけを試す
        ok, error = win32.set_foreground(hwnd)
        if ok and win32.foreground_window() == hwnd:
            logger.info("[instance] 起動済みのウィンドウを前面に出しました（2つ目から）")
            return True
        win32.flash(hwnd)
        logger.warning("[instance] 前面化に失敗したため、タスクバーで点滅させました（エラー %d）", error)
        return False
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("[instance] 起動済みのウィンドウを前面に出せません")
        return False
