"""外部依存の同梱と CSP（Phase 4）の静的チェック。"""
import base64
import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "src" / "ui"
INDEX = UI / "index.html"
FONTS = UI / "fonts"
VENDOR = UI / "vendor"


def own_ui_files():
    """自前の UI ファイル（同梱ライブラリは除く）"""
    for p in UI.rglob("*"):
        if p.suffix in (".html", ".css", ".js") and VENDOR not in p.parents:
            yield p


def csp_directives():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<meta http-equiv="Content-Security-Policy"\s+content="([^"]*)"', html)
    assert m, "CSP meta tag not found"
    directives = {}
    for part in m.group(1).split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    return directives


def readme_hashes(readme):
    """README.md の「sha256  ファイル名」行を読む"""
    text = readme.read_text(encoding="utf-8")
    return dict((name, h) for h, name in re.findall(r"^([0-9a-f]{64})\s+(\S+)\s*$", text, flags=re.M))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- 外部への読み込みが無いこと -----------------------------------------------

@pytest.mark.parametrize("path", sorted(own_ui_files()), ids=lambda p: str(p.relative_to(UI)))
def test_no_external_urls(path):
    text = path.read_text(encoding="utf-8")
    assert re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}/", text, flags=re.I) is None
    if path.suffix == ".css":
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        assert "@import" not in code


def test_index_loads_only_local_assets():
    html = INDEX.read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not re.match(r"^[a-z]+:|^//", ref, flags=re.I), ref
        assert (UI / ref).is_file(), ref


# --- CSP ----------------------------------------------------------------------

def test_csp_directives():
    d = csp_directives()
    assert d["default-src"] == ["'self'"]
    assert d["script-src"] == ["'self'"]
    assert d["img-src"] == ["'self'", "data:"]
    assert d["font-src"] == ["'self'"]
    assert d["connect-src"] == ["'self'"]
    assert d["object-src"] == ["'none'"]
    assert d["base-uri"] == ["'none'"]
    assert d["form-action"] == ["'none'"]
    style = d["style-src"]
    assert style[0] == "'self'"
    assert all(s.startswith("'sha256-") for s in style[1:])


def test_csp_has_no_unsafe_keywords():
    for name, values in csp_directives().items():
        for v in values:
            assert not v.startswith("'unsafe-"), (name, v)


def test_csp_style_hash_matches_pywebview():
    """pywebview が差し込む <style> のハッシュと一致すること（pywebview 更新時の検知用）"""
    import webview
    js = (Path(webview.__file__).parent / "js" / "customize.js").read_text(encoding="utf-8")
    css = re.search(r"var disableTextCss = '([^']*)'", js).group(1)
    expected = "'sha256-" + base64.b64encode(hashlib.sha256(css.encode()).digest()).decode() + "'"
    assert expected in csp_directives()["style-src"]


# --- 同梱物とライセンス -------------------------------------------------------

def test_vendor_files_match_readme():
    hashes = readme_hashes(VENDOR / "README.md")
    assert set(hashes) == {"Sortable.min.js", "Sortable.LICENSE"}
    for name, h in hashes.items():
        assert sha256(VENDOR / name) == h, name
    assert "Sortable 1.15.0" in (VENDOR / "Sortable.min.js").read_text(encoding="utf-8")[:80]


def test_font_files_match_readme():
    """フォントとライセンス文書が、記録した SHA-256（取得元と同じバイト列）と一致すること"""
    hashes = readme_hashes(FONTS / "README.md")
    bundled = {p.name for p in FONTS.iterdir()
               if p.suffix in (".ttf", ".woff2") or p.name.startswith("OFL-")}
    # README には変換前の元ファイルのハッシュも載っているため、包含関係で確認する
    assert bundled <= set(hashes), bundled - set(hashes)
    for name in bundled:
        assert sha256(FONTS / name) == hashes[name], name


def _git_check_attr(*paths):
    import shutil
    import subprocess
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("git リポジトリではない")
    out = subprocess.run(["git", "check-attr", "text", "binary", "eol", "--", *paths],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    attrs = {}
    for line in out.splitlines():
        path, attr, value = line.rsplit(": ", 2)
        attrs.setdefault(path, {})[attr] = value
    return attrs


def test_gitattributes_keeps_bundled_files_unconverted():
    """core.autocrlf があっても同梱物の改行が変換されないこと（ハッシュ検証が壊れないように）"""
    paths = ["src/ui/vendor/Sortable.min.js", "src/ui/vendor/Sortable.LICENSE",
             "src/ui/fonts/fonts.css", "src/ui/fonts/OFL-oswald.txt",
             "src/ui/fonts/NotoSansJP-Variable.woff2", "src/ui/fonts/Orbitron-Variable.ttf"]
    attrs = _git_check_attr(*paths)
    for p in paths:
        assert attrs[p]["text"] == "unset", p


def test_gitattributes_binary_and_text_rules():
    attrs = _git_check_attr("icon.ico", "build.ps1", "src/api.py", "src/ui/script.js")
    assert attrs["icon.ico"]["binary"] == "set"
    assert attrs["icon.ico"]["text"] == "unset"
    for p in ("build.ps1", "src/api.py", "src/ui/script.js"):
        assert attrs[p]["eol"] == "crlf", p


def test_fonts_css_references_existing_files():
    css = (FONTS / "fonts.css").read_text(encoding="utf-8")
    refs = re.findall(r"url\('([^']+)'\)", css)
    assert refs
    for ref in refs:
        assert (FONTS / ref).is_file(), ref


@pytest.mark.parametrize("family, license_file", [
    ("Orbitron", "OFL-orbitron.txt"),
    ("Teko", "OFL-teko.txt"),
    ("Shippori Mincho", "OFL-shipporimincho.txt"),
    ("Silkscreen", "OFL-silkscreen.txt"),
    ("Cinzel", "OFL-cinzel.txt"),
    ("Noto Sans JP", "OFL-notosansjp.txt"),
    ("Oswald", "OFL-oswald.txt"),
])
def test_each_font_has_ofl(family, license_file):
    css = (FONTS / "fonts.css").read_text(encoding="utf-8")
    assert f"font-family: '{family}'" in css
    text = (FONTS / license_file).read_text(encoding="utf-8")
    assert "SIL Open Font License, Version 1.1" in text


def test_every_font_family_used_in_css_is_bundled():
    """テーマ等で指定しているフォントがすべて fonts.css で定義されていること（汎用ファミリー等を除く）"""
    generic = {"sans-serif", "serif", "monospace", "inherit", "courier new"}
    defined = set(re.findall(r"font-family: '([^']+)'", (FONTS / "fonts.css").read_text(encoding="utf-8")))
    for path in [UI / "style.css", *sorted((UI / "themes").glob("*.css"))]:
        for decl in re.findall(r"font-family:\s*([^;]+);", path.read_text(encoding="utf-8")):
            for fam in decl.split(","):
                fam = fam.strip().strip("'\"")
                if fam.lower() not in generic:
                    assert fam in defined, f"{path.name}: {fam}"


# --- PyInstaller --------------------------------------------------------------

def test_spec_bundles_ui_and_example():
    spec = (ROOT / "PaletteLaunch.spec").read_text(encoding="utf-8")
    assert "os.path.join(ROOT, 'src', 'ui'), os.path.join('src', 'ui')" in spec
    assert "os.path.join(ROOT, 'settings.json.example'), '.'" in spec
    assert "console=False" in spec
    assert "COLLECT(" in spec  # onedir


def test_pyinstaller_is_pinned():
    req = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^pyinstaller==\d", req, flags=re.M)
    assert re.search(r"^pyinstaller-hooks-contrib==\d", req, flags=re.M)
