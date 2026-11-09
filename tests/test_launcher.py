"""src/core/launcher.py のテスト。

Windows 専用モジュール（win32com, os.startfile）と subprocess はすべてモックする。
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


def test_url_scheme_opens_with_startfile(launcher, startfile, popen):
    """URL スキームは OS の関連付け（os.startfile）で開く"""
    assert launcher.launch_app("steam://rungameid/570") is True
    startfile.assert_called_once_with("steam://rungameid/570")
    popen.assert_not_called()


def test_launch_failure_returns_false(launcher, startfile):
    """起動時に例外が出たら False を返す"""
    startfile.side_effect = OSError("boom")
    assert launcher.launch_app("steam://rungameid/570") is False
