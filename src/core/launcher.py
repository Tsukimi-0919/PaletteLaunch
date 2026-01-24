import os
import win32com.client
import configparser
import subprocess


def launch_app(path):
    """
    パスまたはURLを指定してアプリを起動する。
    """
    try:
        if path.startswith(('steam://', 'riot://', 'http')):
            # URLスキーム（Steam等）の場合は、OSの関連付けで開く
            os.startfile(path)
        else:
            # 通常の実行ファイルの場合
            subprocess.Popen(path, cwd=os.path.dirname(path))
        return True
    except Exception as e:
        print(f"起動失敗: {e}")
        return False


def resolve_shortcut(path):
    """
    .lnk および .url ファイルから実体/起動用パスを抽出する。
    """
    ext = path.lower()

    # 1. 通常のショートカット (.lnk)
    if ext.endswith('.lnk'):
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(path)
            return shortcut.TargetPath if shortcut.TargetPath else path
        except:
            return path

    # 2. インターネットショートカット (.url) - Valorant/Apex等
    if ext.endswith('.url'):
        try:
            config = configparser.ConfigParser()
            config.read(path)
            # [InternetShortcut] セクションの URL キーを取得
            return config.get('InternetShortcut', 'URL')
        except:
            return path

    return path
