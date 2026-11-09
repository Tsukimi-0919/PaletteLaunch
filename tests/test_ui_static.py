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
