"""PaletteLaunch のバージョン（唯一の管理場所）。

build.ps1 がこの行を読み取り、配布用 zip の名前（PaletteLaunch-v<version>-win64.zip）に使う。
リリース時はここを更新してコミットし、同じ番号の git タグ（v<version>）を付ける。
"""
__version__ = "1.4.0"
