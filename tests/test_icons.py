"""src/core/icons.py のテスト（Phase 6: 透明なアイコンを失敗として扱う）。

Steam の .ico（例: OVR Advanced Settings）は 32x32 のフレームが2枚あり、
1枚は 32bpp の本物、もう1枚は 1bpp の空フレーム（色データ 0・マスクがすべて透明）。
Pillow は同じサイズのフレームを1枚しか使わず、空フレームを選ぶため透明になっていた。
"""
import base64
import logging
import struct
from io import BytesIO
from unittest import mock

import pytest
from PIL import Image

from src.core import icons


def _dib_32bpp(size, opaque_pixels):
    """32bpp の BMP（ICO 内の形式。高さは XOR+AND の2倍）。左下から opaque_pixels 個を赤の不透明にする"""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytearray()
    for i in range(size * size):
        pixels += bytes((0, 0, 255, 255)) if i < opaque_pixels else bytes((0, 0, 0, 0))
    row = ((size + 31) // 32) * 4
    mask = bytes(row * size)  # AND マスクは 0（alpha を使う）
    return header + bytes(pixels) + mask


def _dib_1bpp_blank(size):
    """1bpp の空フレーム（色データ 0、AND マスクはすべて 1 = 透明）"""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 1, 0, 0, 0, 0, 2, 0)
    palette = bytes(8)
    row = ((size + 31) // 32) * 4
    return header + palette + bytes(row * size) + b"\xff" * (row * size)


def make_ico(frames):
    """frames: [(size, bpp, dib_bytes)] をディレクトリ順に並べた ICO"""
    out = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    body = b""
    for size, bpp, dib in frames:
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, bpp, len(dib), offset)
        offset += len(dib)
        body += dib
    return out + body


def steam_like_ico(opaque_pixels=568):
    return make_ico([(32, 32, _dib_32bpp(32, opaque_pixels)), (32, 1, _dib_1bpp_blank(32))])


def decode(data_uri):
    assert data_uri.startswith("data:image/webp;base64,")
    return Image.open(BytesIO(base64.b64decode(data_uri.split(",", 1)[1])))


def webp_uri(img):
    out = BytesIO()
    img.save(out, format="WEBP")
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()


def test_fixture_reproduces_pillow_choosing_blank_frame(tmp_path):
    """前提の確認: Pillow の既定の選び方では透明になる（修正前の不具合の再現）"""
    path = tmp_path / "steam.ico"
    path.write_bytes(steam_like_ico())
    with Image.open(path) as img:
        assert img.convert("RGBA").getchannel("A").getextrema() == (0, 0)


def test_steam_like_ico_uses_visible_frame(tmp_path):
    path = tmp_path / "steam.ico"
    path.write_bytes(steam_like_ico())
    data = icons.get_icon_base64(str(path))
    img = decode(data)
    assert img.size == (48, 48)
    assert not icons.is_blank_image(img)
    assert icons.is_blank_icon_data(data) is False


def test_all_blank_ico_returns_empty(tmp_path):
    path = tmp_path / "blank.ico"
    path.write_bytes(make_ico([(32, 1, _dib_1bpp_blank(32)), (16, 1, _dib_1bpp_blank(16))]))
    assert icons.get_icon_base64(str(path)) == ""


def test_almost_blank_ico_returns_empty(tmp_path):
    """不透明な画素が 1% 未満（32x32 で 10 画素未満）なら空とみなす"""
    path = tmp_path / "almost.ico"
    path.write_bytes(steam_like_ico(opaque_pixels=5))
    assert icons.get_icon_base64(str(path)) == ""


def test_prefers_larger_visible_frame(tmp_path):
    path = tmp_path / "multi.ico"
    path.write_bytes(make_ico([(16, 32, _dib_32bpp(16, 256)), (32, 32, _dib_32bpp(32, 1024)),
                               (48, 1, _dib_1bpp_blank(48))]))
    img = decode(icons.get_icon_base64(str(path)))
    # 32x32 の全面不透明フレームが選ばれる（48 の空フレーム・16 のフレームではない）
    assert img.convert("RGBA").getchannel("A").getextrema()[0] > 200


@pytest.mark.parametrize("alpha,expected_blank", [(0, True), (255, False)])
def test_png(tmp_path, alpha, expected_blank):
    path = tmp_path / "icon.png"
    Image.new("RGBA", (64, 64), (10, 20, 30, alpha)).save(path)
    result = icons.get_icon_base64(str(path))
    assert (result == "") is expected_blank


def test_exe_icon_frames_are_checked(tmp_path, monkeypatch):
    """exe から取り出したアイコン（ICO 形式）も同じ選び方をする"""
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    extractor = mock.MagicMock()
    extractor.return_value.get_icon.return_value = BytesIO(steam_like_ico())
    monkeypatch.setattr(icons, "IconExtractor", extractor)
    data = icons.get_icon_base64(str(exe), 0)
    assert data and not icons.is_blank_icon_data(data)
    extractor.return_value.get_icon.assert_called_once_with(num=0)


def test_exe_all_blank_returns_empty(tmp_path, monkeypatch):
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    extractor = mock.MagicMock()
    extractor.return_value.get_icon.return_value = BytesIO(make_ico([(32, 1, _dib_1bpp_blank(32))]))
    monkeypatch.setattr(icons, "IconExtractor", extractor)
    assert icons.get_icon_base64(str(exe)) == ""


def test_extraction_error_is_logged_without_print(tmp_path, monkeypatch, caplog, capsys):
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(icons, "IconExtractor", mock.MagicMock(side_effect=ValueError("bad")))
    with caplog.at_level(logging.WARNING, logger="src.core.icons"):
        assert icons.get_icon_base64(str(exe)) == ""
    assert "game.exe" in caplog.text
    assert capsys.readouterr().out == ""


# --- 保存済みのアイコンの判定 -------------------------------------------------

def test_is_blank_icon_data():
    assert icons.is_blank_icon_data(webp_uri(Image.new("RGBA", (48, 48), (0, 0, 0, 0))))
    assert not icons.is_blank_icon_data(webp_uri(Image.new("RGBA", (48, 48), (255, 0, 0, 255))))


@pytest.mark.parametrize("value", [
    "", None, 123, "data:image/png;base64,AAAA", "data:image/webp;base64,!!!",
    "data:image/webp;base64,AAAA",
])
def test_is_blank_icon_data_ignores_invalid(value):
    assert icons.is_blank_icon_data(value) is False
