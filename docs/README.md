# PALETTE LAUNCH

自作のテーマと言語切り替えに対応した、軽量なデスクトップランチャー。

## 構成

* `main.py` : バックエンド (pywebview)
* `index.html` : 構造
* `style.css` : デザイン（標準・小サイズ切り替え）
* `script.js` : 制御（DOM生成・多言語化）
* `lang/` : 翻訳データ (ja.json / en.json)

## 仕様メモ

### 表示モード

| モード | CSSクラス | 内容 |
| :--- | :--- | :--- |
| **標準** | `.size-medium` | アイコン(48px) + アプリ名 |
| **小** | `.size-small` | アイコン(40px) のみ。高密度表示。 |

### 小サイズの微調整 (Tips)

* カテゴリ名の垂直中央がズレるため、`transform: translateY(-2px)` で補正済み。
* カードの `padding` を `0` にし、`gap` を `10px` に凝縮。

## 起動

```bash
python main.py
```
