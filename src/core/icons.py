"""
実行ファイル(.exe)からアイコンを抽出し、軽量なWebP形式のBase64文字列に変換するモジュール。
"""

import base64
import os
from io import BytesIO
from icoextract import IconExtractor
from PIL import Image


def get_icon_base64(path):
    """
    指定されたパス(EXE, LNK, URL, ICO等)からアイコンを取得し、
    48x48のWebP形式でBase64エンコードして返す。
    """
    if not path or not os.path.exists(path):
        return ""

    try:
        ext = path.lower()
        img = None

        # 1. 直接画像ファイル (.ico, .png, .jpg) の場合
        if ext.endswith(('.ico', '.png', '.jpg', '.jpeg')):
            img = Image.open(path)

        # 2. 実行ファイル (.exe) 等の場合
        else:
            extractor = IconExtractor(path)
            icon_bytes_io = extractor.get_icon()
            img = Image.open(icon_bytes_io)

        if img:
            # 透明度を維持したままRGBAに変換（JPG対策）
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # 3. Pillowによるリサイズ処理 (48x48)
            img = img.resize((48, 48), Image.Resampling.LANCZOS)

            # 4. WebP形式でメモリに保存
            output = BytesIO()
            img.save(output, format="WEBP", quality=80)
            icon_data = output.getvalue()

            # 5. Base64文字列に変換
            base64_str = base64.b64encode(icon_data).decode('utf-8')
            return f"data:image/webp;base64,{base64_str}"

    except Exception as e:
        # DOS Header magic not found 等のエラーもここでキャッチされます
        print(f"Extraction Failed for {path}: {e}")
        return ""

    return ""
