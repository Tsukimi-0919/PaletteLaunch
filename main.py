"""
PaletteLaunch のメインエントリーポイント。
GUIウィンドウを生成し、バックエンドAPIをバインドします。
"""
import logging
import sys
import os
import webview
from webview.dom import DOMEventHandler
from src.api import API
from src.core import single_instance
from src.core.drop_guard import DropGuard
from src.core.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def get_resource_path(relative_path):
    """HTMLや画像など、変更しないアセット用（EXE内部を指す）"""
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(
        os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def get_config_path(filename):
    """settings.jsonなど、更新される設定ファイル用（EXEの隣を指す）"""
    # EXE実行時はEXEがあるディレクトリ、スクリプト実行時はスクリプトのディレクトリ
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)


def register_drop_handler(window, api, drop_guard):
    """
    ページの読み込み完了時に、document の drop を Python 側で受け取るよう登録する（1回だけ）。
    ドロップの検証（DropGuard）が無効なら登録しない（検証なしでは受け付けない）。
    """
    if not drop_guard.enabled:
        logger.warning("ドロップの検証が無効なため、ドロップでの追加は使えません")
        return

    state = {"registered": False}

    def on_loaded():
        if state["registered"]:
            return
        state["registered"] = True
        # prevent_default: ファイルをページ外にドロップしても WebView が開かないようにする
        window.dom.document.events.drop += DOMEventHandler(api._handle_drop, True, False)  # pylint: disable=protected-access

    window.events.loaded += on_loaded


def main():
    """
    アプリケーションのメインループを起動する。
    """
    log_path = setup_logging()
    logger.info("PaletteLaunch を起動します（ログ: %s）", log_path)

    # 二重起動の防止（ハンドルは終了まで保持する）
    mutex = single_instance.acquire()
    if mutex is None:
        logger.info("すでに起動しているため終了します")
        single_instance.activate_existing()
        return

    # settings.json の正しい外付けパスを取得（EXE の隣）
    settings_path = get_config_path('settings.json')
    # 初回起動時のひな形（EXE 内部の _internal を指す）
    example_path = get_resource_path('settings.json.example')

    # ドロップで受け取るパスの検証（理由は src/core/drop_guard.py を参照）
    drop_guard = DropGuard()
    drop_guard.install()

    # APIインスタンスの生成（どちらも絶対パスで渡す）
    api = API(os.path.abspath(settings_path), os.path.abspath(example_path),
              drop_guard=drop_guard)

    # UI（HTML）のパスを取得
    html_path = get_resource_path(os.path.join("src", "ui", "index.html"))

    # ウィンドウの作成（タイトルは二重起動時のウィンドウ探しにも使う）
    window = webview.create_window(
        single_instance.WINDOW_TITLE,
        html_path,
        js_api=api,
        width=1000,
        height=700,
        background_color='#0f1923'
    )
    api._attach_window(window)  # pylint: disable=protected-access
    register_drop_handler(window, api, drop_guard)

    # 二重起動のとき、2つ目がこのウィンドウを前面に出せるように PID とウィンドウを記録する
    host = single_instance.InstanceHost()
    window.events.shown += host.publish

    try:
        webview.start(debug=False)
    finally:
        host.close()
        del mutex


if __name__ == '__main__':
    main()
