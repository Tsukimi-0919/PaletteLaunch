# ARCHITECTURE

システムの構造とデータの流れ。

## 技術スタック

* **Backend:** Python 3.12 / `pywebview` 6.1（Edge WebView2）/ Pillow・icoextract（アイコン）/ pywin32（.lnk の読み取り・二重起動の防止）
* **Frontend:** HTML5, CSS3, Vanilla JS（並べ替えは同梱の Sortable.js）
* **Fonts:** すべて `src/ui/fonts/` に同梱（OFL）。外部への通信はしない（CSP で `'self'` のみ許可）。

| フォント | 使っているところ |
| :--- | :--- |
| Oswald | 共通（`style.css`） |
| Orbitron | Valorant / Cyberpunk |
| Teko | Apex |
| Cinzel | MHW / Hydrangea |
| Shippori Mincho | Hydrangea 系（日本語の明朝体） |
| Silkscreen | Minecraft |
| Noto Sans JP | Starry、各テーマの日本語 |

同梱物の出どころ・ハッシュ・更新手順は `src/ui/fonts/README.md` と `src/ui/vendor/README.md`（`tests/test_bundle.py` でハッシュを検査）。

## ファイル構成と役割

| ファイル | 役割 |
| :--- | :--- |
| `main.py` | 起動の入口。ログの設定、二重起動の防止（`single_instance`）、`settings.json`（EXE の隣）と `settings.json.example`（EXE 内部）の絶対パスの解決、ドロップの検証（`DropGuard`）の準備、ウィンドウの作成と `API` の登録を行う。設定の読み書きはしない。 |
| `src/api.py` | JS から呼ばれる API（`js_api`）。公開メソッドはすべて JS から呼べるため、入力（パス・拡張子・名前・設定値・並び順）はここで検証する。内部用のメソッドは `_` で始める。 |
| `src/core/config.py` | `ConfigManager`: `settings.json` の読み書きを一手に引き受ける。絶対パスだけを受け取り、読み込み時にスキーマを補完し（旧形式も読む）、書き込みは原子的に行う。`.bak`・日ごとのバックアップ・壊れたファイルの退避と、読めなかったときの読み取り専用モードを持つ（docs/backup.md）。 |
| `src/core/launcher.py` | 起動処理。`.exe` は `Popen([path])`、`.lnk` / `.url` / `.bat` と許可したスキームの URL は `os.startfile`。.lnk / .url の読み取りもここ。 |
| `src/core/icons.py` | アイコンを 48×48 の WebP（data URI）にする。ICO は透明でないフレームを選ぶ。 |
| `src/core/drop_guard.py` | ドロップされたファイルのパスの検証（下記）。 |
| `src/core/single_instance.py` | 二重起動の防止と、起動済みのウィンドウの前面化（下記）。 |
| `src/core/logging_setup.py` | ログファイルの設定（下記）。 |
| `src/version.py` | バージョン番号の唯一の置き場所（docs/build.md）。 |
| `src/ui/index.html` | UI の骨組み。CSP の meta タグを持つ。 |
| `src/ui/style.css` | 共通レイアウト、サイズ（標準/小）、操作部品の大きさの変数。 |
| `src/ui/themes/*.css` | テーマごとの色・枠・フォント・装飾。ファイルを置くと `get_themes()` の一覧に出る。 |
| `src/ui/script.js` | DOM の生成（`createElement` + `textContent`。`innerHTML` は使わない）、多言語化、テーマ・サイズの反映、並べ替え・ドロップ。 |
| `src/ui/lang/*.json` | 表示文字列（ja / en）。 |
| `settings.json` | ユーザー設定（テーマ、言語、サイズ、カテゴリー、ショートカット）。EXE と同じフォルダに置かれ、git 管理外・配布 zip にも含めない。 |

## データフロー

1. **起動:** `main.py` が二重起動を確かめてから `API` を作る。`API` の中の `ConfigManager` が `settings.json` を読む（無ければ example から作る。壊れていれば退避して `.bak` から復元、だめなら読み取り専用）。
2. **初期化:** `pywebviewready`（または準備済みなら即時）で JS の `init()` が1回だけ動く。`renderApp()` が `get_themes()`（テーマの一覧）と `get_config()`（全データ）を取得して描画し、`loadAndApplySettings()` が言語・サイズなどの設定を反映し、最後に `notifyLoadStatus()` が `get_load_status()` で読み込み結果（読み取り専用・復元など）を知らせる。
3. **適用:**
   * テーマ → `#theme-link` の `href` を `themes/<名前>.css` にし、`body` のテーマのクラスだけを差し替える（全上書きはしない）
   * `#app-container` クラス → `size-small` / `size-medium` 反映
   * `applyLabels()` → `lang/*.json` を元に UI テキストを更新
4. **保存:** UI の操作ごとに JS が API（`update_setting`、`add_shortcut`、`save_order` など）を呼び、Python 側で検証してから `ConfigManager` が `settings.json` に保存する。JS から設定全体を書き込む API は無い。

## 実装の急所

* **`#app-container`**: 表示サイズの切り替えはこの要素のクラスで行う。
* **`translateY(-2px)`**: `small` モード時、カテゴリ名の垂直位置を補正するためのマジックナンバー。
* **`line-height: 1`**: 文字の上下余白を消し、計算通りのセンター配置を実現するために多用。
* **操作部品の大きさ（`--control-*` / `--action-*`）**: ヘッダーの選択欄・「＋カテゴリー」と、カテゴリー見出しのボタンの高さ・幅・余白・文字サイズ・角丸は `style.css` の変数だけで決める。テーマ CSS には色・枠・フォントの種類・装飾だけを書き、大きさを変えたいときはテーマの `:root` で変数を上書きする（`tests/test_ui_static.py` で検査）。
* **ドラッグ＆ドロップのパス検証（`src/core/drop_guard.py`）**: pywebview 6.1 では、ドロップしたファイルのフルパス（`pywebviewFullPath`）を JS から偽装できる。そのため、pywebview の内部データ `webview.dom._dnd_state['paths']` を記録用のリストに差し替え、WebView2 のネイティブ側から来たパスだけを信頼している。この仕組みが使えないとき（バージョン違いなど）は、ドロップでの追加を無効にする。pywebview を更新するときは `docs/security-fix-plan.md` の Phase 6「ドロップのパス検証」を読むこと。
* **ログ**: `%LOCALAPPDATA%\PaletteLaunch\logs\palettelaunch.log`（1MB × 3世代）。アイコンの base64 や設定ファイルの中身全体はログに出さない。
* **二重起動の防止**: ユーザーごとの名前付きミューテックス（`Local\PaletteLaunch.SingleInstance.<SID>`）。1つ目は PID とウィンドウハンドルを `%LOCALAPPDATA%\PaletteLaunch\instance.json` に記録し、名前付きイベント（`Local\PaletteLaunch.Activate.<SID>`）で前面化の依頼を待つ。2つ目は記録のウィンドウが記録の PID のものでタイトルも一致することを確かめてから、`AllowSetForegroundWindow` で権限を渡して依頼する。実行ファイル名では見分けない（.venv の python はランチャーで、ウィンドウを持つのは子プロセスのため）。ログは `[instance]`。
* **ドラッグ中の強調**: ファイルをドラッグしている間、カーソルの下のカテゴリーに `.drop-target`（`--accent-color` の点線の枠）を付ける。ファイル以外のドラッグ（Sortable の並べ替え）では付けない。
* **ヘッダーの部品の幅は固定**: テーマや言語を切り替えても位置がずれないように、全テーマのフォント・両言語でいちばん長い表示が収まる幅にしてある。テーマやフォントを足したときは測り直す。
