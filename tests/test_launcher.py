"""src/core/launcher.py のテスト。

Windows 専用モジュール（win32com, os.startfile）と subprocess はすべてモックする。
ファイルの存在チェックや .url の読み込みは tmp_path 上の実ファイルで確認する。
"""
import importlib
import sys
from unittest import mock

import pytest


@pytest.fixture
def launcher(monkeypatch):
    """win32com をモックに差し替えた状態で launcher モジュールを読み込む"""
    win32com = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", win32com.client)
    monkeypatch.delitem(sys.modules, "src.core.launcher", raising=False)
    module = importlib.import_module("src.core.launcher")
    yield module
    sys.modules.pop("src.core.launcher", None)


@pytest.fixture
def startfile(launcher, monkeypatch):
    """os.startfile のモック（非 Windows 環境でも動くよう raising=False）"""
    m = mock.MagicMock()
    monkeypatch.setattr(launcher.os, "startfile", m, raising=False)
    return m


@pytest.fixture
def popen(launcher, monkeypatch):
    """subprocess.Popen のモック"""
    m = mock.MagicMock()
    monkeypatch.setattr(launcher.subprocess, "Popen", m)
    return m


def make_file(tmp_path, name, content="", encoding="utf-8"):
    p = tmp_path / name
    p.write_text(content, encoding=encoding)
    return str(p)


def make_url_file(tmp_path, url, name="game.url", encoding="utf-8"):
    return make_file(tmp_path, name,
                     f"[InternetShortcut]\nURL={url}\n", encoding=encoding)


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
    popen.assert_called_once_with([path], cwd=str(tmp_path))
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
