"""
ドラッグ＆ドロップで受け取ったファイルのフルパスを「本当にドロップされたもの」だけに絞る。

■ なぜ pywebview の内部データ（webview.dom._dnd_state['paths']）を差し替えるのか
  pywebview 6.1 では、ドロップしたファイルのフルパスは Python 側の DOM イベント
  ハンドラーに渡る event の files[i]['pywebviewFullPath'] でしか受け取れない。
  ところが webview/util.py（pywebviewEventHandler の処理）は、ネイティブ側で記録した
  パスとファイル名が一致したときだけ pywebviewFullPath を上書きし、一致しなければ
  JS から送られてきた値をそのまま残す。JS から
      pywebview._jsApiCallback('pywebviewEventHandler',
          {event: {type: 'drop', dataTransfer: {files: [{name, pywebviewFullPath}]}},
           nodeId: 'document'}, 'eventHandler')
  を呼ぶと、任意のパスをハンドラーに届けられる（2026-11 に WebView2 の実機で確認）。

  一方 _dnd_state['paths'] には、WebView2 のネイティブメッセージ "FilesDropped"
  （edgechromium.py の on_script_notify）からしか追加されない。中身は WebView2 が渡す
  CoreWebView2File.Path で、WebView2 は「ディスク上の実ファイル」以外の File を
  postMessageWithAdditionalObjects で送らせない（JS で作った File は拒否される）。
  そこで _dnd_state['paths'] を、追加（+=）を記録するリストに差し替え、記録にある
  パスだけを信頼する。

■ 安全側に倒す
  差し替えが効かない（pywebview のバージョン違い・内部構造の変化・差し替えの失敗）
  ときは enabled = False になり、ドロップでの追加は無効になる。検証なしで受け付ける
  方向には倒さない。

■ この仕組みを外してよい条件（pywebview を更新する人へ）
  - pywebview が、JS から送られた pywebviewFullPath を必ず消す（または上書きする）
    ようになった、または
  - ネイティブ側で取得したパスを、JS を経由せずに Python へ渡す公開 API ができた。
  どちらかを新しいバージョンのソースで確認し、tests/test_drop_guard.py の偽装テスト
  （方法 A）が新しい仕組みでも弾かれることを確かめてから外すこと。
  それまでは requirements.txt で pywebview を == で固定し、EXPECTED_PYWEBVIEW_VERSION
  と合わせて更新すること。
"""
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# この仕組みを確認した pywebview のバージョン（requirements.txt と合わせる）
EXPECTED_PYWEBVIEW_VERSION = "6.1"
# ドロップの記録の有効期限（秒）
DROP_TTL_SECONDS = 30.0


def _norm(path):
    """比較用に正規化する。正規化できない値（NUL を含むなど）は None"""
    try:
        return os.path.normcase(os.path.abspath(path))
    except (TypeError, ValueError):
        return None


def _installed_pywebview_version():
    from importlib import metadata  # pylint: disable=import-outside-toplevel
    try:
        return metadata.version("pywebview")
    except metadata.PackageNotFoundError:
        return None


class _RecordingPaths(list):
    """
    _dnd_state['paths'] の代わりに置くリスト。
    pywebview のネイティブ側の「_dnd_state['paths'] += files」を guard に知らせる。
    remove など他の操作は通常のリストと同じ（pywebview 側の処理を変えない）。
    """

    def __init__(self, guard, initial=()):
        super().__init__(initial)
        self._guard = guard

    def __iadd__(self, other):
        items = list(other)
        try:
            self._guard._record_native(items)  # pylint: disable=protected-access
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("ドロップの記録に失敗しました")
        return super().__iadd__(items)


class DropGuard:
    """ネイティブ側で取得したドロップのパスを記録し、照合する"""

    def __init__(self, ttl=DROP_TTL_SECONDS, clock=time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._trusted = {}   # 正規化したパス -> 元のパス（最後の1回のドロップ分）
        self._recorded_at = None
        self.enabled = False

    # --- 差し替え ---------------------------------------------------------------

    def install(self, dnd_state=None, version=None):
        """
        pywebview の _dnd_state['paths'] を記録用のリストに差し替える。
        成功したら True（enabled = True）。少しでも想定と違えば False のまま。
        dnd_state / version はテスト用（省略時は実物を使う）。
        """
        self.enabled = False
        try:
            if version is None:
                version = _installed_pywebview_version()
            if version != EXPECTED_PYWEBVIEW_VERSION:
                logger.warning("pywebview %s は未確認のバージョンです（確認済み: %s）。"
                               "ドロップでの追加を無効にします",
                               version, EXPECTED_PYWEBVIEW_VERSION)
                return False

            if dnd_state is None:
                # pylint: disable=import-outside-toplevel
                import webview.dom
                import webview.util
                dnd_state = webview.dom._dnd_state  # pylint: disable=protected-access
                # util.py も同じ dict を参照していること（from webview.dom import _dnd_state）
                if getattr(webview.util, "_dnd_state", None) is not dnd_state:
                    logger.warning("pywebview の内部構造が想定と違います（util._dnd_state）。"
                                   "ドロップでの追加を無効にします")
                    return False

            if not isinstance(dnd_state, dict) or \
                    not isinstance(dnd_state.get("paths"), list) or \
                    "num_listeners" not in dnd_state:
                logger.warning("pywebview の内部構造が想定と違います（_dnd_state）。"
                               "ドロップでの追加を無効にします")
                return False

            current = dnd_state["paths"]
            if isinstance(current, _RecordingPaths) and current._guard is self:  # pylint: disable=protected-access
                self.enabled = True
                return True

            recorder = _RecordingPaths(self, current)
            dnd_state["paths"] = recorder
            if dnd_state.get("paths") is not recorder:
                logger.warning("_dnd_state の差し替えに失敗しました。ドロップでの追加を無効にします")
                return False
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("_dnd_state の差し替えに失敗しました。ドロップでの追加を無効にします")
            return False

        self.enabled = True
        logger.info("ドロップの検証を有効にしました（pywebview %s）", version)
        return True

    # --- 記録と照合 -------------------------------------------------------------

    def _record_native(self, items):
        """ネイティブ側（WebView2 の FilesDropped）から届いた (name, path) の一覧を記録する"""
        trusted = {}
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                continue
            path = item[1]
            key = _norm(path) if isinstance(path, str) and path else None
            if key:
                trusted[key] = path
        with self._lock:
            # 記録は最後の1回のドロップ分だけ
            self._trusted = trusted
            self._recorded_at = self._clock()
        logger.info("ドロップを受け取りました（%d 件）", len(trusted))

    def consume(self, claimed_paths):
        """
        event に載っていたパスのうち、ネイティブ側の記録にあるものだけを返す。
        呼ぶと記録は消える（使ったら消す）。期限切れ・無効時は空のリスト。
        """
        with self._lock:
            trusted, recorded_at = self._trusted, self._recorded_at
            self._trusted, self._recorded_at = {}, None

        if not self.enabled or recorded_at is None:
            return []
        if self._clock() - recorded_at > self._ttl:
            logger.warning("ドロップの記録が期限切れです")
            return []

        accepted, seen = [], set()
        for path in claimed_paths:
            key = _norm(path) if isinstance(path, str) and path else None
            if key and key in trusted and key not in seen:
                seen.add(key)
                accepted.append(trusted[key])
        rejected = len(claimed_paths) - len(accepted)
        if rejected:
            logger.warning("ネイティブ側の記録に無いドロップのパスを %d 件拒否しました", rejected)
        return accepted
