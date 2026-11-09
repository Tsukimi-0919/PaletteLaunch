"""src/core/launcher.py のテスト。

Windows 専用モジュール（win32com, os.startfile）と subprocess はすべてモックする。
ファイルの存在チェックや .url の読み込みは tmp_path 上の実ファイルで確認する。
"""
import subprocess
from unittest import mock

import pytest

from tests.helpers import make_file, make_url_file

UNC_EXE = "\\\\server\\share\\a.exe"


# --- URL スキーム -------------------------------------------------------------

def test_url_scheme_opens_with_startfile(launcher, startfile, popen):
    """URL スキームは OS の関連付け（os.startfile）で開く"""
    assert launcher.launch_app("steam://rungameid/570") is True
    startfile.assert_called_once_with("steam://rungameid/570")
    popen.assert_not_called()


@pytest.mark.parametrize("url", [
    "STEAM://rungameid/570",
    "riot://launch",
    "https://example.com/",
    "Http://example.com/",
    "com.epicgames.launcher://apps/Fortnite?action=launch",
])
def test_allowed_schemes(launcher, startfile, url):
    assert launcher.launch_app(url) is True
    startfile.assert_called_once_with(url)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "file:///C:/Windows/System32/calc.exe",
    "ms-settings:privacy",
    "httpx://example.com/",
    "steamx://run",
])
def test_disallowed_schemes(launcher, startfile, popen, url):
    assert launcher.launch_app(url) is False
    startfile.assert_not_called()
    popen.assert_not_called()


def test_drive_letter_is_not_url(launcher, startfile, popen, tmp_path):
    """C:\\... はスキーム "c" の URL ではなくファイルパスとして扱う"""
    path = make_file(tmp_path, "game.exe")
    assert launcher._get_scheme(path) is None
    assert launcher.launch_app(path) is True
    popen.assert_called_once()
    startfile.assert_not_called()


# --- 拡張子別の分岐 -----------------------------------------------------------

@pytest.mark.parametrize("name", ["game.exe", "GAME.EXE"])
def test_exe_uses_popen_with_list(launcher, startfile, popen, tmp_path, name):
    path = make_file(tmp_path, name)
    assert launcher.launch_app(path) is True
    popen.assert_called_once_with([path], cwd=str(tmp_path),
                                  creationflags=subprocess.CREATE_NEW_CONSOLE)
    startfile.assert_not_called()


@pytest.mark.parametrize("name", ["game.lnk", "GAME.LNK"])
def test_lnk_opens_original_file_without_cwd(launcher, startfile, popen, tmp_path, name):
    """.lnk は解析せず、作業フォルダもショートカット側の設定に任せる"""
    path = make_file(tmp_path, name)
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path)
    popen.assert_not_called()


def test_bat_opens_with_own_folder_as_cwd(launcher, startfile, popen, tmp_path):
    path = make_file(tmp_path, "start.BAT")
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path, cwd=str(tmp_path))
    popen.assert_not_called()


@pytest.mark.parametrize("name", ["setup.msi", "readme.txt", "script.ps1", "noext"])
def test_disallowed_extension(launcher, startfile, popen, tmp_path, name, caplog):
    path = make_file(tmp_path, name)
    with caplog.at_level("WARNING"):
        assert launcher.launch_app(path) is False
    startfile.assert_not_called()
    popen.assert_not_called()
    assert path in caplog.text
    assert "拡張子" in caplog.text


# --- .url ---------------------------------------------------------------------

def test_url_file_with_allowed_url_opens_original_file(launcher, startfile, popen, tmp_path):
    path = make_url_file(tmp_path, "steam://rungameid/570")
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path)
    popen.assert_not_called()


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/System32/calc.exe",
    "ms-settings:privacy",
    r"C:\Windows\System32\calc.exe",
])
def test_url_file_with_disallowed_url_is_rejected(launcher, startfile, popen, tmp_path, url):
    path = make_url_file(tmp_path, url)
    assert launcher.launch_app(path) is False
    startfile.assert_not_called()
    popen.assert_not_called()


@pytest.mark.parametrize("content", [
    "",                                   # 空
    "[InternetShortcut]\nIconIndex=0\n",  # URL キーなし
    "URL=steam://rungameid/570\n",        # セクションなし
])
def test_unreadable_url_file_is_rejected(launcher, startfile, tmp_path, content):
    path = make_file(tmp_path, "broken.url", content)
    assert launcher.launch_app(path) is False
    startfile.assert_not_called()


# --- 存在チェック・失敗時 -----------------------------------------------------

@pytest.mark.parametrize("name", ["missing.exe", "missing.lnk", "missing.url", "missing.bat"])
def test_missing_file_returns_false(launcher, startfile, popen, tmp_path, name, caplog):
    path = str(tmp_path / name)
    with caplog.at_level("WARNING"):
        assert launcher.launch_app(path) is False
    startfile.assert_not_called()
    popen.assert_not_called()
    assert path in caplog.text


def test_directory_is_rejected(launcher, startfile, popen, tmp_path):
    assert launcher.launch_app(str(tmp_path)) is False
    startfile.assert_not_called()
    popen.assert_not_called()


@pytest.mark.parametrize("value", ["", None])
def test_empty_path_returns_false(launcher, startfile, popen, value):
    assert launcher.launch_app(value) is False
    startfile.assert_not_called()
    popen.assert_not_called()


def test_launch_failure_returns_false(launcher, startfile):
    """起動時に例外が出たら False を返す"""
    startfile.side_effect = OSError("boom")
    assert launcher.launch_app("steam://rungameid/570") is False


def _winerror(code):
    e = OSError(f"WinError {code}")
    e.winerror = code
    return e


def test_elevation_required_falls_back_to_startfile(launcher, startfile, popen, tmp_path):
    """WinError 740（管理者権限が必要）のときは startfile で UAC を出す"""
    path = make_file(tmp_path, "admin.exe")
    popen.side_effect = _winerror(740)
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path, cwd=str(tmp_path))


def test_other_oserror_does_not_fall_back(launcher, startfile, popen, tmp_path):
    path = make_file(tmp_path, "broken.exe")
    popen.side_effect = _winerror(193)  # 有効な Win32 アプリケーションではない
    assert launcher.launch_app(path) is False
    startfile.assert_not_called()


# --- read_url_file / resolve_shortcut -----------------------------------------

def test_read_url_file_keeps_percent(launcher, tmp_path):
    """% を含む URL でも展開せずに読める"""
    url = "https://example.com/a%20b?x=%41"
    parser = launcher.read_url_file(make_url_file(tmp_path, url))
    assert parser.get("InternetShortcut", "URL") == url


def test_read_url_file_utf8_bom(launcher, tmp_path):
    parser = launcher.read_url_file(
        make_url_file(tmp_path, "steam://rungameid/570", encoding="utf-8-sig"))
    assert parser.get("InternetShortcut", "URL") == "steam://rungameid/570"


def test_read_url_file_cp932(launcher, tmp_path):
    path = make_file(tmp_path, "jp.url",
                     "[InternetShortcut]\nURL=steam://rungameid/1\nIconFile=C:\\ゲーム\\icon.ico\n",
                     encoding="cp932")
    parser = launcher.read_url_file(path)
    assert parser.get("InternetShortcut", "IconFile") == "C:\\ゲーム\\icon.ico"


def test_read_url_file_duplicate_keys(launcher, tmp_path):
    path = make_file(tmp_path, "dup.url",
                     "[InternetShortcut]\nURL=steam://a\nURL=steam://b\n")
    assert launcher.read_url_file(path) is not None


@pytest.mark.parametrize("content", ["not an ini file", "[broken"])
def test_read_url_file_broken_returns_none(launcher, tmp_path, content):
    assert launcher.read_url_file(make_file(tmp_path, "bad.url", content)) is None


def test_read_url_file_missing_returns_none(launcher, tmp_path):
    assert launcher.read_url_file(str(tmp_path / "missing.url")) is None


def test_resolve_shortcut_url(launcher, tmp_path):
    path = make_url_file(tmp_path, "steam://rungameid/570")
    assert launcher.resolve_shortcut(path) == "steam://rungameid/570"


def test_resolve_shortcut_broken_url_returns_path(launcher, tmp_path):
    path = make_file(tmp_path, "bad.url", "garbage")
    assert launcher.resolve_shortcut(path) == path


# --- .lnk のリンク先チェック（Phase 2 追加項目） --------------------------------

def test_lnk_with_missing_target_is_rejected(launcher, win32_mocks, startfile, popen,
                                             tmp_path, caplog):
    """リンク先が存在しない .lnk は startfile を呼ばない（「ショートカットの検索」を出さない）"""
    path = make_file(tmp_path, "moved.lnk")
    missing = str(tmp_path / "gone" / "game.exe")
    win32_mocks.shortcut.TargetPath = missing
    with caplog.at_level("WARNING"):
        assert launcher.launch_app(path) is False
    startfile.assert_not_called()
    popen.assert_not_called()
    assert missing in caplog.text


def test_lnk_with_existing_target_opens(launcher, win32_mocks, startfile, tmp_path):
    path = make_file(tmp_path, "ok.lnk")
    win32_mocks.shortcut.TargetPath = make_file(tmp_path, "game.exe")
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path)


@pytest.mark.parametrize("target", [
    "",                       # シェルフォルダ・MSI アドバタイズ等
    "game.exe",               # 相対パス
    UNC_EXE,                  # UNC は存在チェックしない（SMB 接続させない）
])
def test_lnk_with_special_target_is_left_to_startfile(launcher, win32_mocks, startfile,
                                                      tmp_path, monkeypatch, target):
    path = make_file(tmp_path, "special.lnk")
    win32_mocks.shortcut.TargetPath = target
    exists = mock.MagicMock(return_value=False)
    monkeypatch.setattr(launcher.os.path, "exists", exists)
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path)
    exists.assert_not_called()


def test_lnk_unreadable_is_left_to_startfile(launcher, win32_mocks, startfile, tmp_path):
    path = make_file(tmp_path, "weird.lnk")
    win32_mocks.win32com.client.Dispatch.side_effect = RuntimeError("COM error")
    assert launcher.launch_app(path) is True
    startfile.assert_called_once_with(path)


# --- get_lnk_info / COM の初期化 ----------------------------------------------

def test_get_lnk_info_returns_target_and_icon(launcher, win32_mocks):
    win32_mocks.shortcut.TargetPath = r"C:\Games\game.exe"
    win32_mocks.shortcut.IconLocation = r"C:\Games\game.exe,1"
    assert launcher.get_lnk_info(r"C:\x.lnk") == {
        "target": r"C:\Games\game.exe", "icon_location": r"C:\Games\game.exe,1"}
    win32_mocks.pythoncom.CoInitialize.assert_called_once()
    win32_mocks.pythoncom.CoUninitialize.assert_called_once()


def test_get_lnk_info_uninitializes_on_error(launcher, win32_mocks):
    """COM の例外時も CoInitialize / CoUninitialize が対になる"""
    win32_mocks.win32com.client.Dispatch.side_effect = RuntimeError("COM error")
    assert launcher.get_lnk_info(r"C:\x.lnk") is None
    win32_mocks.pythoncom.CoInitialize.assert_called_once()
    win32_mocks.pythoncom.CoUninitialize.assert_called_once()


def test_get_lnk_info_skips_uninitialize_if_initialize_fails(launcher, win32_mocks):
    win32_mocks.pythoncom.CoInitialize.side_effect = RuntimeError("init failed")
    with pytest.raises(RuntimeError):
        launcher.get_lnk_info(r"C:\x.lnk")
    win32_mocks.pythoncom.CoUninitialize.assert_not_called()


def test_resolve_shortcut_lnk(launcher, win32_mocks):
    win32_mocks.shortcut.TargetPath = r"C:\Games\game.exe"
    assert launcher.resolve_shortcut(r"C:\x.lnk") == r"C:\Games\game.exe"


def test_resolve_shortcut_lnk_without_target_returns_path(launcher):
    assert launcher.resolve_shortcut(r"C:\x.lnk") == r"C:\x.lnk"


# --- 判定ヘルパー -------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (r"C:\Games\game.exe,0", (r"C:\Games\game.exe", 0)),
    (r"C:\Games\game.exe,3", (r"C:\Games\game.exe", 3)),
    (r"C:\Windows\System32\shell32.dll,-16769", (r"C:\Windows\System32\shell32.dll", -16769)),
    (r'"C:\Games\game.exe",2', (r"C:\Games\game.exe", 2)),
    (r"C:\Games\icon.ico", (r"C:\Games\icon.ico", 0)),
    (",0", None),
    ("", None),
    (None, None),
])
def test_parse_icon_location(launcher, value, expected):
    assert launcher.parse_icon_location(value) == expected


def test_parse_icon_location_expands_env(launcher, monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    assert launcher.parse_icon_location(r"%SystemRoot%\System32\shell32.dll,4") == (
        r"C:\Windows\System32\shell32.dll", 4)


@pytest.mark.parametrize("path, expected", [
    (UNC_EXE, True),
    ("//server/share/a.exe", True),
    ("\\\\?\\C:\\a.exe", True),
    (r"C:\a.exe", False),
    ("", False),
    (None, False),
])
def test_is_unc_path(launcher, path, expected):
    assert launcher.is_unc_path(path) is expected


def test_is_missing_drive_target(launcher, tmp_path):
    assert launcher.is_missing_drive_target(str(tmp_path / "nope.exe")) is True
    assert launcher.is_missing_drive_target(make_file(tmp_path, "a.exe")) is False
    assert launcher.is_missing_drive_target("") is False
    assert launcher.is_missing_drive_target("relative.exe") is False
    assert launcher.is_missing_drive_target(UNC_EXE) is False
