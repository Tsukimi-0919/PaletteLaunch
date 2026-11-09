"""
実行ファイル(.exe)からアイコンを抽出し、軽量なWebP形式のBase64文字列に変換するモジュール。
"""

import base64
import binascii
import functools
import logging
import os
import warnings
from io import BytesIO

from icoextract import IconExtractor
from PIL import Image

logger = logging.getLogger(__name__)

ICON_SIZE = (48, 48)
_DATA_URI_PREFIX = "data:image/webp;base64,"

# 「ほぼ透明」の判定: alpha が _VISIBLE_ALPHA 以上の画素が全体の _MIN_VISIBLE_RATIO 未満なら空とみなす
_VISIBLE_ALPHA = 16
_MIN_VISIBLE_RATIO = 0.01


def is_blank_image(img):
    """画像がすべて（またはほぼすべて）透明なら True"""
    rgba = img if img.mode == "RGBA" else img.convert("RGBA")
    total = rgba.width * rgba.height
    if total == 0:
        return True
    histogram = rgba.getchannel("A").histogram()
    visible = sum(histogram[_VISIBLE_ALPHA:])
    return visible < total * _MIN_VISIBLE_RATIO


def is_blank_icon_data(data_uri):
    """
    保存済みのアイコン（data:image/webp;base64,...）が透明なら True。
    デコードできないものは False（表示側の形式チェックに任せる）。
    """
    if not isinstance(data_uri, str) or not data_uri.startswith(_DATA_URI_PREFIX):
        return False
    return _is_blank_icon_data_cached(data_uri)


@functools.lru_cache(maxsize=512)
def _is_blank_icon_data_cached(data_uri):
    try:
        raw = base64.b64decode(data_uri[len(_DATA_URI_PREFIX):], validate=True)
        with Image.open(BytesIO(raw)) as img:
            img.load()
            return is_blank_image(img)
    except (binascii.Error, OSError, ValueError, Image.DecompressionBombError):
        return False


def _ico_frames(img):
    """
    ICO の全フレームを「大きいサイズ → 色深度が高い」の順に返す。
    Pillow は同じサイズのフレームが複数あると1枚しか使わない（Steam の .ico では
    1bpp の空フレームが選ばれて透明になる）ため、自分で全フレームを並べる。
    """
    entries = list(enumerate(img.ico.entry))
    entries.sort(key=lambda e: (e[1].width * e[1].height, e[1].bpp), reverse=True)
    for i, _entry in entries:
        try:
            # ディレクトリのサイズと中身のサイズが違うフレームで出る警告は無視する
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                frame = img.ico.frame(i)
            yield frame
        except (OSError, ValueError, SyntaxError) as e:
            logger.debug("ICO のフレーム %d を読めません: %s", i, e)


def _candidate_frames(img):
    if img.format == "ICO":
        yield from _ico_frames(img)
    else:
        yield img


def _encode(frame):
    """透明でなければ 48x48 の WebP data URI を返す。透明なら None"""
    rgba = frame if frame.mode == "RGBA" else frame.convert("RGBA")
    if is_blank_image(rgba):
        return None
    resized = rgba.resize(ICON_SIZE, Image.Resampling.LANCZOS)
    if is_blank_image(resized):
        return None
    output = BytesIO()
    resized.save(output, format="WEBP", quality=80)
    return _DATA_URI_PREFIX + base64.b64encode(output.getvalue()).decode("ascii")


def get_icon_base64(path, index=0):
    """
    指定されたパス(EXE, LNK, URL, ICO等)からアイコンを取得し、
    48x48のWebP形式でBase64エンコードして返す。
    index は EXE/DLL 内のアイコン番号（IconLocation の ",0" など）。
    すべてのフレームが透明（またはほぼ透明）なら "" を返す（呼び出し側が次の候補を試す）。
    """
    # UNC パスは存在チェックだけで SMB 接続が発生する（NTLM ハッシュ漏えい対策）
    if not path or path.startswith(("\\\\", "//")):
        return ""
    if not os.path.exists(path):
        return ""

    try:
        # 1. 直接画像ファイル (.ico, .png, .jpg) の場合
        if path.lower().endswith(('.ico', '.png', '.jpg', '.jpeg')):
            source = path
        # 2. 実行ファイル (.exe) 等の場合（中身は ICO 形式）
        else:
            extractor = IconExtractor(path)
            # 負のインデックスはリソース ID 指定（例: ",-101" → ID 101）
            if index < 0:
                source = extractor.get_icon(resource_id=-index)
            else:
                source = extractor.get_icon(num=index)

        with Image.open(source) as img:
            for frame in _candidate_frames(img):
                data = _encode(frame)
                if data:
                    return data
        logger.info("アイコンがすべて透明なため使いません: %s", path)
        return ""

    except Exception as e:  # pylint: disable=broad-exception-caught
        # DOS Header magic not found 等のエラーもここでキャッチされます
        logger.warning("アイコンを取得できません: %s (%s)", path, e)
        return ""
