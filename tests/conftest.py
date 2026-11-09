"""共通フィクスチャ。

Windows 専用モジュール（win32com, pythoncom, os.startfile）と subprocess はモックする。
"""
import importlib
import sys
from unittest import mock

import pytest


@pytest.fixture
def win32_mocks(monkeypatch):
    """win32com / pythoncom をモックに差し替え、src.core.launcher と src.api を読み直させる"""
    win32com = mock.MagicMock()
    pythoncom = mock.MagicMock()
    # 既定は「リンク先・アイコン指定のない .lnk」
    shortcut = win32com.client.Dispatch.return_value.CreateShortcut.return_value
    shortcut.TargetPath = ""
    shortcut.IconLocation = ""

    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", win32com.client)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    for name in ("src.core.launcher", "src.api"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield mock.NonCallableMock(win32com=win32com, pythoncom=pythoncom,
                               shortcut=shortcut)
    for name in ("src.core.launcher", "src.api"):
        sys.modules.pop(name, None)


@pytest.fixture
def launcher(win32_mocks):
    return importlib.import_module("src.core.launcher")


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

