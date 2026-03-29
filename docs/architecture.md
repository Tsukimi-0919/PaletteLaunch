# ARCHITECTURE

システムの構造とデータの流れ。

## 技術スタック

* **Backend:** Python (`pywebview`)
* **Frontend:** HTML5, CSS3, Vanilla JS
* **Fonts:** Oswald (Google Fonts)

## ファイル構成と役割

| ファイル | 役割 |
| :--- | :--- |
| `main.py` | ウィンドウ生成。`settings.json` の読み書きAPIを提供。 |
| `settings.json` | ユーザー設定（テーマ、言語、サイズ、ショートカット）の保存先。 |
| `index.html` | UIの骨組み。JSによる動的描画のベース。 |
| `style.css` | 共通レイアウト、各テーマの変数、サイズ（標準/小）の制御。 |
| `script.js` | `settings.json` の反映、多言語化、DOM生成の全ロジック。 |

## データフロー

1. **起動:** `main.py` が `settings.json` をロード。
2. **初期化:** JSが `get_config()` で全データを一括取得。
3. **適用:** * `body` クラス → テーマ反映
   * `#app-container` クラス → `size-small` / `size-medium` 反映
   * `applyLabels()` → `lang/*.json` を元にUIテキストを更新
4. **保存:** ユーザーがUI（セレクトボックス等）を変更すると、JS経由で `settings.json` が即座に更新される。

## 実装の急所

* **`#app-container`**: 表示サイズの切り替えはこの要素のクラスで行う。
* **`translateY(-2px)`**: `small` モード時、カテゴリ名の垂直位置を補正するためのマジックナンバー。
* **`line-height: 1`**: 文字の上下余白を消し、計算通りのセンター配置を実現するために多用。
