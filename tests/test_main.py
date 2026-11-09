"""main.py のテスト: 設定ファイルと example を絶対パスで渡していること（Phase 5 #7）"""
import importlib
import os
import sys
from unittest import mock

import pytest


@pytest.fixture
def main_module(win32_mocks, monkeypatch):
    monkeypatch.delitem(sys.modules, "main", raising=False)
    module = importlib.import_module("main")
    yield module
    sys.modules.pop("main", None)


def test_main_passes_absolute_paths(main_module, monkeypatch):
    api_cls = mock.MagicMock()
    monkeypatch.setattr(main_module, "API", api_cls)
    monkeypatch.setattr(main_module.webview, "create_window", mock.MagicMock())
    monkeypatch.setattr(main_module.webview, "start", mock.MagicMock())

    main_module.main()

    settings_path, example_path = api_cls.call_args.args
    root = os.path.dirname(os.path.abspath(main_module.__file__))
    assert os.path.isabs(settings_path) and os.path.isabs(example_path)
    assert settings_path == os.path.join(root, "settings.json")
    assert example_path == os.path.join(root, "settings.json.example")
    assert os.path.isfile(example_path)


def test_frozen_paths(main_module, monkeypatch, tmp_path):
    """EXE では settings.json は EXE の隣、example は _internal（_MEIPASS）の中"""
    exe = tmp_path / "PaletteLaunch" / "PaletteLaunch.exe"
    internal = tmp_path / "PaletteLaunch" / "_internal"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    assert main_module.get_config_path("settings.json") == str(exe.parent / "settings.json")
    assert main_module.get_resource_path("settings.json.example") == \
        str(internal / "settings.json.example")
