"""バージョン管理と build.ps1（配布用 zip）の静的チェック。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_PS1 = ROOT / "build.ps1"


def test_version_format():
    from src.version import __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_build_ps1_reads_the_same_version_line():
    """build.ps1 の正規表現で src/version.py が読めること"""
    text = (ROOT / "src" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'(?m)^__version__\s*=\s*"(\d+\.\d+\.\d+)"\s*$', text)
    from src.version import __version__
    assert m and m.group(1) == __version__
    assert r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"\s*$' in BUILD_PS1.read_text(encoding="utf-8-sig")


def test_build_ps1_has_bom_for_windows_powershell():
    """Windows PowerShell 5.1 は BOM なし UTF-8 を ANSI として読むため BOM が必要"""
    assert BUILD_PS1.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_build_ps1_zip_name_and_exclusions():
    text = BUILD_PS1.read_text(encoding="utf-8-sig")
    assert '"PaletteLaunch-v$Version-win64.zip"' in text
    for pattern in ("'settings.json'", "'settings.json.bak'", "'settings.corrupt-*.json'"):
        assert pattern in text
    # zip の検査（必須ファイル・除外ファイル）を行っていること
    assert "zip に含めてはいけないファイルがあります" in text
    assert "PaletteLaunch/_internal/src/ui/index.html" in text


def test_build_ps1_does_not_pass_double_quotes_to_python():
    """PowerShell 5.1 は外部コマンドの引数から " を落とすため、python -c に " を使わない"""
    for line in BUILD_PS1.read_text(encoding="utf-8-sig").splitlines():
        m = re.search(r"\$Python\s+-c\s+'([^']*)'", line)
        if m:
            assert '"' not in m.group(1), line
