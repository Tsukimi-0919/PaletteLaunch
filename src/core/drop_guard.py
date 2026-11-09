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
  パスだけを信頼する。event の pywebviewFullPath は「どの記録か」を選ぶ手がかりに
  使うだけで、受け付けるパスは常に記録（ネイティブ側）の値にする。

■ 到着順が逆になることへの対策
  pywebview の JS は、ドロップのたびに FilesDropped（postMessageWithAdditionalObjects）
  と DOM イベント（postMessage）を続けて送るが、File を受け渡す前者の方が後に届くことが
  ある。その場合 pywebview はファイル名で照合できず pywebviewFullPath が付かない。
  そこで consume() は記録が届くまで最大 NATIVE_WAIT_SECONDS 待ち、届いた記録と
  ファイル名で照合する（pywebview 自身と同じ照合方法）。待っても記録が無ければ受け付けない。

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
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# この仕組みを確認した pywebview のバージョン（requirements.txt と合わせる）
EXPECTED_PYWEBVIEW_VERSION = "6.1"
# ドロップの記録の有効期限（秒）
DROP_TTL_SECONDS = 30.0
# DOM イベントが先に届いたとき、ネイティブ側の記録を待つ時間（秒）
NATIVE_WAIT_SECONDS = 2.0

# 拒否の理由（API・UI のエラーコードにも使う）
REASON_DISABLED = "drop_disabled"
REASON_NO_RECORD = "drop_no_native_record"
REASON_EXPIRED = "drop_expired"
REASON_NOT_RECORDED = "drop_not_recorded"
REASON_NO_FILES = "drop_no_files"


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


@dataclass
class DropCheck:
    """consume() の結果"""
    accepted: list = field(default_factory=list)   # 受け付けたパス（ネイティブ側の値）
    rejected: list = field(default_factory=list)   # [(ファイル名, 理由)]
    reason: str = None                             # 1件も受け付けなかったときの代表の理由


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

    def __init__(self, ttl=DROP_TTL_SECONDS, wait=NATIVE_WAIT_SECONDS, clock=time.monotonic):
        self._ttl = ttl
        self._wait = wait
        self._clock = clock
        self._cond = threading.Condition()
        self._trusted = []   # [(ファイル名, パス)]（最後の1回のドロップ分）
        self._recorded_at = None
        self._recorder = None
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
                self._recorder = current
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

        self._recorder = recorder
        self.enabled = True
        logger.info("ドロップの検証を有効にしました（pywebview %s）", version)
        return True

    # --- 記録と照合 -------------------------------------------------------------

    def _record_native(self, items):
        """ネイティブ側（WebView2 の FilesDropped）から届いた (name, path) の一覧を記録する"""
        trusted = []
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                continue
            name, path = item
            if isinstance(path, str) and path and _norm(path):
                trusted.append((name if isinstance(name, str) else os.path.basename(path), path))
        with self._cond:
            # 記録は最後の1回のドロップ分だけ
            self._trusted = trusted
            self._recorded_at = self._clock()
            self._cond.notify_all()
        logger.info("[drop 1/5] ネイティブの記録（FilesDropped）を受け取りました: %d 件 %s",
                    len(trusted), [n for n, _ in trusted])

    def _take_record(self):
        """記録を取り出して消す。記録が届くまで最大 self._wait 秒待つ"""
        with self._cond:
            if self._recorded_at is None and self._wait > 0:
                logger.info("[drop 3/5] ネイティブの記録がまだ無いため、最大 %.1f 秒待ちます",
                            self._wait)
                self._cond.wait_for(lambda: self._recorded_at is not None, timeout=self._wait)
            trusted, recorded_at = self._trusted, self._recorded_at
            self._trusted, self._recorded_at = [], None
        return trusted, recorded_at

    def _forget_in_pywebview(self, entries):
        """使った記録を pywebview 側のリストからも消す（次のドロップで誤って照合されないように）"""
        recorder = self._recorder
        if recorder is None:
            return
        for entry in entries:
            try:
                list.remove(recorder, entry)
            except ValueError:
                pass  # pywebview がすでに消した

    def consume(self, files):
        """
        DOM の drop イベントの files（[{name, pywebviewFullPath?}, ...]）をネイティブ側の
        記録と照合する。受け付けるパスは常に記録の値。呼ぶと記録は消える（使ったら消す）。
        """
        result = DropCheck()
        files = [f for f in (files or []) if isinstance(f, dict)]
        if not self.enabled:
            result.reason = REASON_DISABLED
            result.rejected = [(f.get("name"), REASON_DISABLED) for f in files]
            logger.warning("[drop 3/5] ドロップの検証が無効なため拒否しました")
            return result
        if not files:
            result.reason = REASON_NO_FILES
            logger.warning("[drop 3/5] drop イベントにファイルが含まれていないため拒否しました")
            return result

        trusted, recorded_at = self._take_record()
        if recorded_at is None:
            result.reason = REASON_NO_RECORD
            result.rejected = [(f.get("name"), REASON_NO_RECORD) for f in files]
            logger.warning("[drop 3/5] %.1f 秒待ってもネイティブの記録が届かないため拒否しました: %s",
                           self._wait, [f.get("name") for f in files])
            return result
        if self._clock() - recorded_at > self._ttl:
            result.reason = REASON_EXPIRED
            result.rejected = [(f.get("name"), REASON_EXPIRED) for f in files]
            logger.warning("[drop 3/5] ネイティブの記録が期限切れ（%.0f 秒）のため拒否しました",
                           self._ttl)
            return result

        remaining = list(trusted)
        used = []
        for f in files:
            name, claimed = f.get("name"), f.get("pywebviewFullPath")
            entry = None
            key = _norm(claimed) if isinstance(claimed, str) and claimed else None
            if key:
                entry = next((e for e in remaining if _norm(e[1]) == key), None)
            if entry is None and isinstance(name, str) and name:
                # pywebview と同じく、ファイル名で記録と照合する（到着順が逆のとき）
                entry = next((e for e in remaining if e[0] == name), None)
            if entry is None:
                result.rejected.append((name, REASON_NOT_RECORDED))
                continue
            remaining.remove(entry)
            used.append(entry)
            if entry[1] not in result.accepted:
                result.accepted.append(entry[1])

        self._forget_in_pywebview(used)
        if result.rejected:
            logger.warning("[drop 3/5] ネイティブの記録と照合できないファイルを拒否しました: %s",
                           [n for n, _ in result.rejected])
        if not result.accepted:
            result.reason = REASON_NOT_RECORDED
        logger.info("[drop 3/5] 照合の結果: 受け付け %d 件、拒否 %d 件",
                    len(result.accepted), len(result.rejected))
        return result
