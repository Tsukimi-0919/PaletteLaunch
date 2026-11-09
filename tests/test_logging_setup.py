"""src/core/logging_setup.py のテスト（Phase 6: print をやめてログファイルへ）"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from src.core import logging_setup

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def clean_root():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield root
    for handler in list(root.handlers):
        if handler not in saved_handlers:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(saved_level)


def test_writes_rotating_log(tmp_path, clean_root):
    path = logging_setup.setup_logging(log_dir=str(tmp_path / "logs"), console=False)
    assert path == str(tmp_path / "logs" / "palettelaunch.log")
    handlers = [h for h in clean_root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == logging_setup.MAX_BYTES
    assert handlers[0].backupCount == logging_setup.BACKUP_COUNT

    logging.getLogger("src.test").warning("こんにちは")
    handlers[0].flush()
    assert "こんにちは" in Path(path).read_text(encoding="utf-8")


def test_default_dir_is_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logging_setup.default_log_dir() == str(tmp_path / "PaletteLaunch" / "logs")


def test_unwritable_dir_does_not_crash(tmp_path, clean_root):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert logging_setup.setup_logging(log_dir=str(blocker / "logs"), console=False) is None


def test_no_print_in_app_code():
    for path in [ROOT / "main.py", *(ROOT / "src").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "print(" not in text, path
