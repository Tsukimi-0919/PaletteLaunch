"""UI（src/ui）の静的チェック。XSS 対策（Phase 3）の回帰防止。

保存データを HTML として解釈させる API や、インラインのイベント属性を使っていないことを確認する。
"""
import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parent.parent / "src" / "ui"
SCRIPT_JS = UI_DIR / "script.js"
INDEX_HTML = UI_DIR / "index.html"


def js_code_without_comments(text):
    """// と /* */ のコメントを除いた JS（文字列内の // は script.js に無い前提の簡易版）"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@pytest.fixture(scope="module")
def script_code():
    return js_code_without_comments(SCRIPT_JS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("pattern", [
    r"\.innerHTML\b",
    r"\.outerHTML\b",
    r"\binsertAdjacentHTML\b",
    r"\bdocument\.write(ln)?\b",
    r"\beval\s*\(",
    r"\bnew\s+Function\s*\(",
    r"\bsetAttribute\(\s*['\"]on",
])
def test_script_does_not_use_html_injection_apis(script_code, pattern):
    assert re.search(pattern, script_code) is None


def test_script_has_no_inline_handlers_in_strings(script_code):
    assert re.search(r"\bon[a-z]+\s*=\s*['\"]", script_code) is None


def test_index_html_has_no_inline_handlers():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert re.search(r"<[^>]+\son[a-z]+\s*=", html, flags=re.I) is None


def test_icon_src_is_restricted_to_webp_data_uri():
    text = SCRIPT_JS.read_text(encoding="utf-8")
    assert r"/^data:image\/webp;base64," in text
    # img.src への代入は許可パターンを通した 1 か所だけ
    assert len(re.findall(r"\.src\s*=", js_code_without_comments(text))) == 1


def test_single_initialization(script_code):
    assert len(re.findall(r"pywebviewready", script_code)) == 1
    assert len(re.findall(r"\bfunction\s+applyTheme\b", script_code)) == 1
    assert "get_settings" not in script_code
    assert "body.className" not in script_code


# --- Phase 5: 設定ファイルの状態の通知 ------------------------------------------

LANG_DIR = UI_DIR / "lang"
PHASE5_KEYS = ["error_read_only", "error_save_failed", "notice_read_only",
               "notice_restored", "notice_recreated", "notice_corrupt_copy"]


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_phase5_messages_exist(lang):
    import json
    messages = json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    for key in PHASE5_KEYS:
        assert isinstance(messages.get(key), str) and messages[key], key
    assert "{file}" in messages["notice_corrupt_copy"]


def test_api_methods_called_from_js_are_public(script_code):
    """script.js が呼ぶ API は、すべて公開名の一覧（tests/test_api.py）に入っていること"""
    from tests.test_api import EXPECTED_PUBLIC
    called = set(re.findall(r"pywebview\.api\.(\w+)", script_code))
    assert "get_load_status" in called
    assert called <= EXPECTED_PUBLIC, called - EXPECTED_PUBLIC


def test_every_save_checks_the_result(script_code):
    """保存する API の結果を捨てずに確認していること（読み取り専用モードで黙って失敗しない）"""
    for method in ("update_setting", "add_category", "delete_shortcut", "edit_shortcut",
                   "delete_category", "edit_category", "save_order"):
        calls = re.findall(rf"^.*pywebview\.api\.{method}\(.*$", script_code, flags=re.M)
        assert calls, method
        for line in calls:
            assert "if (!(await" in line, line
