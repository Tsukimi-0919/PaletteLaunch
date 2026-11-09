"""main.py のテスト: 設定ファイルと example を絶対パスで渡していること（Phase 5 #7）、
二重起動防止とドロップのハンドラー登録（Phase 6）"""
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


@pytest.fixture
def started(main_module, monkeypatch):
    """main() の外部への作用（ログ・ミューテックス・pywebview・_dnd_state）をすべてモックする"""
    m = mock.NonCallableMock()
    m.setup_logging = mock.MagicMock(return_value=None)
    m.acquire = mock.MagicMock(return_value="handle")
    m.activate = mock.MagicMock(return_value=True)
    m.api_cls = mock.MagicMock()
    m.guard = mock.MagicMock(enabled=True)
    m.create_window = mock.MagicMock()
    m.start = mock.MagicMock()
    monkeypatch.setattr(main_module, "setup_logging", m.setup_logging)
    monkeypatch.setattr(main_module.single_instance, "acquire", m.acquire)
    monkeypatch.setattr(main_module.single_instance, "activate_existing", m.activate)
    monkeypatch.setattr(main_module, "API", m.api_cls)
    monkeypatch.setattr(main_module, "DropGuard", lambda: m.guard)
    monkeypatch.setattr(main_module.webview, "create_window", m.create_window)
    monkeypatch.setattr(main_module.webview, "start", m.start)
    return m


def test_main_passes_absolute_paths(main_module, started):
    main_module.main()

    settings_path, example_path = started.api_cls.call_args.args
    root = os.path.dirname(os.path.abspath(main_module.__file__))
    assert os.path.isabs(settings_path) and os.path.isabs(example_path)
    assert settings_path == os.path.join(root, "settings.json")
    assert example_path == os.path.join(root, "settings.json.example")
    assert os.path.isfile(example_path)
    assert started.api_cls.call_args.kwargs["drop_guard"] is started.guard
    started.guard.install.assert_called_once_with()
    started.start.assert_called_once()


def test_second_instance_does_not_start(main_module, started):
    started.acquire.return_value = None
    main_module.main()
    started.activate.assert_called_once_with()
    started.create_window.assert_not_called()
    started.start.assert_not_called()
    started.api_cls.assert_not_called()


def test_drop_handler_registered_once(main_module):
    window = mock.MagicMock()
    loaded = []
    window.events.loaded.__iadd__ = lambda self, f: loaded.append(f) or self
    api = mock.MagicMock()
    main_module.register_drop_handler(window, api, mock.MagicMock(enabled=True))
    assert len(loaded) == 1

    drop = window.dom.document.events.drop
    loaded[0]()
    loaded[0]()  # ページを読み直しても二重に登録しない
    assert drop.__iadd__.call_count == 1
    handler = drop.__iadd__.call_args.args[0]
    assert handler.callback == api._handle_drop
    assert handler.prevent_default is True


def test_drop_handler_not_registered_when_guard_disabled(main_module):
    """ドロップの検証が無効なら、検証なしで受け付けないよう、ハンドラー自体を登録しない"""
    window = mock.MagicMock()
    main_module.register_drop_handler(window, mock.MagicMock(), mock.MagicMock(enabled=False))
    window.events.loaded.__iadd__.assert_not_called()


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
