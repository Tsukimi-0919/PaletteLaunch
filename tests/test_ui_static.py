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


# --- Phase 8: 操作部品の大きさは style.css の変数だけで決める ----------------------

STYLE_CSS = UI_DIR / "style.css"
THEMES_DIR = UI_DIR / "themes"
THEME_FILES = sorted(THEMES_DIR.glob("*.css"))

# ヘッダーの操作部品（選択欄・＋カテゴリー）とカテゴリーの操作ボタン
CONTROL_SELECTOR = re.compile(
    r"\.add-cat-btn|\.action-btn|\.theme-select|#lang-select|#theme-select"
    r"|#card-size-select|\.header-controls|(?<![\w-])select(?![\w-])")
# 大きさを決めるプロパティ（テーマ側に書くと部品の高さ・幅がテーマごとにずれる）
SIZE_PROPERTY = re.compile(
    r"^(?:(?:min-|max-)?(?:height|width)|padding(?:-\w+)*|font-size|font|line-height"
    r"|margin(?:-\w+)*|box-sizing|flex(?:-\w+)*)$")


def css_rules(path):
    """(セレクター, [(プロパティ, 値)]) の一覧。入れ子の @ ルールは中身だけを拾う簡易版"""
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        decls = []
        for decl in body.split(";"):
            if ":" in decl:
                prop, value = decl.split(":", 1)
                decls.append((prop.strip().lower(), value.strip()))
        rules.append((selector.strip(), decls))
    return rules


def test_theme_files_exist():
    assert len(THEME_FILES) >= 10


@pytest.mark.parametrize("theme", THEME_FILES, ids=lambda p: p.stem)
def test_theme_does_not_size_controls(theme):
    """テーマ CSS は操作部品に大きさ（高さ・幅・余白・文字サイズ）を書かない"""
    bad = [(sel, prop) for sel, decls in css_rules(theme) if CONTROL_SELECTOR.search(sel)
           for prop, _ in decls if SIZE_PROPERTY.match(prop)]
    assert bad == []


@pytest.mark.parametrize("theme", THEME_FILES, ids=lambda p: p.stem)
def test_theme_overrides_size_variables_only_in_root(theme):
    """大きさの変数（--control-* / --action-*）の上書きはテーマの :root だけで行う"""
    for sel, decls in css_rules(theme):
        for prop, _ in decls:
            if re.match(r"--(control|action)-", prop):
                assert sel == ":root", (sel, prop)


def test_style_defines_control_size_variables():
    root = {}
    for sel, decls in css_rules(STYLE_CSS):
        if sel == ":root":
            root.update(decls)
    for name in ("--control-height", "--control-radius", "--control-font-size", "--control-pad-x",
                 "--lang-select-width", "--theme-select-width", "--size-select-width",
                 "--add-cat-width", "--action-height", "--action-font-size",
                 "--action-height-small", "--action-font-size-small"):
        assert name in root, name


def test_header_controls_and_action_buttons_use_variables():
    rules = dict(css_rules(STYLE_CSS))
    header = dict(rules[".header-controls select,\n.header-controls .add-cat-btn"])
    assert header["height"] == "var(--control-height)"
    assert header["font-size"] == "var(--control-font-size)"
    assert header["border-radius"] == "var(--control-radius)"
    action = dict(rules["#app-container .category-actions .action-btn"])
    assert action["height"] == "var(--action-height)"
    assert action["font-size"] == "var(--action-font-size)"
    # 小サイズでは、カテゴリーの帯（28px）に収まる値に切り替わる
    small = dict(rules[".size-small"])
    assert small["--action-height"] == "var(--action-height-small)"


# --- Phase 6: 使い勝手 ---------------------------------------------------------

def test_category_sortable_created_once(script_code):
    assert len(re.findall(r"new\s+Sortable\s*\(\s*container\b", script_code)) == 1
    assert re.search(r"if\s*\(\s*!categorySortable\s*\)", script_code)
    # グリッド用は描き直す前に destroy する
    assert re.search(r"gridSortables\.forEach\([^)]*\.destroy\(\)", script_code)


def test_render_is_serialized(script_code):
    assert re.search(r"\basync\s+function\s+renderAppOnce\b", script_code)
    assert re.search(r"\bfunction\s+renderApp\s*\(\s*\)\s*\{\s*if\s*\(\s*renderRunning\s*\)",
                     script_code)
    # renderAppOnce を直接呼ぶのは renderApp の中だけ
    assert len(re.findall(r"\brenderAppOnce\s*\(", script_code)) == 2  # 定義 + 呼び出し1か所


def test_launch_cooldown(script_code):
    assert re.search(r"const\s+LAUNCH_COOLDOWN_MS\s*=\s*1000\b", script_code)
    assert "launchLockedUntil" in script_code


def test_alerts_are_translated(script_code):
    assert "alert(i18n.error_launch)" in script_code
    # alert に日本語の固定文字列を渡していない
    assert re.search(r"alert\(\s*['\"`][^'\"`]*[\u3040-\u30ff\u4e00-\u9fff]", script_code) is None


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_error_launch_key_exists(lang):
    import json
    data = json.loads((UI_DIR / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    assert data.get("error_launch")


def test_drop_does_not_use_file_path(script_code):
    """WebView2 には file.path が無い。フルパスは Python 側から paletteLaunchOnDrop で届く"""
    assert "file.path ||" not in script_code
    assert "window.paletteLaunchOnDrop = onFilesDropped" in script_code


def test_initial_does_not_split_surrogate_pairs(script_code):
    assert "item.name[0]" not in script_code
    assert "Array.from(item.name)[0]" in script_code


def test_script_syntax_with_node():
    """script.js の構文チェック（node がある環境のみ）"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が見つかりません (node not found on PATH)")
    result = subprocess.run([node, "--check", str(SCRIPT_JS)], capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr


def _drop_error_codes():
    from src.core import drop_guard
    codes = {v for k, v in vars(drop_guard).items() if k.startswith("REASON_")}
    return sorted(codes | {"drop_disabled", "drop_target_missing", "drop_no_response"})


@pytest.mark.parametrize("lang", ["ja", "en"])
@pytest.mark.parametrize("code", _drop_error_codes())
def test_drop_error_messages_exist(lang, code):
    """ドロップで追加されなかったときの理由は、すべて翻訳がある（UI に必ず理由を出す）"""
    import json
    data = json.loads((UI_DIR / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    assert data.get("error_" + code), code


def test_drop_flow_always_reports(script_code):
    assert "pywebview.api.add_dropped_shortcuts(" in script_code
    # Python 側から結果が届かないときも理由を出す
    assert re.search(r"setTimeout\([\s\S]{0,200}error_drop_no_response", script_code)
    # 並べ替え（ファイル以外のドラッグ）は対象外
    assert "types.includes('Files')" in script_code


# --- Phase 6: ドラッグ中のドロップ先の強調 -----------------------------------------

def test_drop_target_style_uses_theme_color():
    rules = dict(css_rules(STYLE_CSS))
    decls = dict(rules[".category-section.drop-target"])
    assert "var(--accent-color)" in decls["outline"]
    # 大きさ・配置を変えるプロパティは使わない（テーマのレイアウトを崩さない）
    assert not any(SIZE_PROPERTY.match(p) for p in decls)


@pytest.mark.parametrize("theme", THEME_FILES, ids=lambda p: p.stem)
def test_every_theme_defines_accent_color(theme):
    assert re.search(r"--accent-color\s*:", theme.read_text(encoding="utf-8"))


def test_drop_highlight_is_cleared(script_code):
    assert re.search(r"addEventListener\('dragleave'[\s\S]{0,120}setDropHighlight\(null\)", script_code)
    assert re.search(r"addEventListener\('drop'[\s\S]{0,80}setDropHighlight\(null\)", script_code)
    assert re.search(r"addEventListener\('dragend'[\s\S]{0,60}setDropHighlight\(null\)", script_code)
    # ファイルのドラッグのときだけ強調する（Sortable の並べ替えでは強調しない）
    assert re.search(r"if \(isFileDrag\(e\)\) setDropHighlight\(", script_code)
