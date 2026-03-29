# アーキテクチャ

## データ構造

設定データは `config.json` に保存され、以下の構造を持ちます。

- `theme`: 現在のテーマ名
- `card_size`: `small` または `medium`
- `categories`: 各カテゴリとショートカットのリスト

## 通信フロー

1. `main.py` が起動。
2. JSが `pywebview.api.get_config()` を呼び出しデータを取得。
3. `script.js` が DOM を動的に生成。
