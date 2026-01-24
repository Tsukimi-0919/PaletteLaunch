"""
PaletteLaunch のメインエントリーポイント。
GUIウィンドウを生成し、バックエンドAPIをバインドします。
"""
import sys
import os
import webview
from src.api import API


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


def main():
    """
    アプリケーションのメインループを起動する。
    """
    # settings.json の正しい外付けパスを取得
    settings_path = get_config_path('settings.json')
    # APIインスタンスの生成
    api = API(settings_path)

    # UI（HTML）のパスを取得
    html_path = get_resource_path(os.path.join("src", "ui", "index.html"))

    # ウィンドウの作成
    # window変数はwebview.start()で内部的に使用されるが、
    # 明示的に使わない場合の警告を回避するため _ を利用するか警告を抑制する
    webview.create_window(
        'PaletteLaunch',
        html_path,
        js_api=api,
        width=1000,
        height=700,
        background_color='#0f1923'
    )

    webview.start(debug=False)


if __name__ == '__main__':
    main()
