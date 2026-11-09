# -*- mode: python ; coding: utf-8 -*-
# PaletteLaunch の PyInstaller 設定（onedir 形式）。
# ビルド手順と起動確認の手順は docs/build.md を参照。
#
#   .venv\Scripts\pyinstaller PaletteLaunch.spec --clean --noconfirm
#
# 出力: dist\PaletteLaunch\PaletteLaunch.exe（settings.json は exe の隣に作られる）
import os

ROOT = SPECPATH  # noqa: F821  （PyInstaller が spec の実行時に定義する）

# UI 一式（index.html, script.js, style.css, themes, lang, vendor, fonts）と
# 初回起動時にコピーする settings.json.example を同梱する。
# 配置先は sys._MEIPASS（onedir では _internal）以下で、main.py / api.py / config.py の
# パス解決（_MEIPASS/src/ui, _MEIPASS/settings.json.example）と対応している。
datas = [
    (os.path.join(ROOT, 'src', 'ui'), os.path.join('src', 'ui')),
    (os.path.join(ROOT, 'settings.json.example'), '.'),
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PaletteLaunch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, 'icon.ico'),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='PaletteLaunch',
)
