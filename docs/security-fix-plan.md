# PaletteLaunch セキュリティ・品質修正計画

2026-11 のコードレビュー結果にもとづく修正計画。
Claude Code は **1セッション＝1フェーズ** で進めること。

## 全体ルール（Claude Code 向け）

- 作業ブランチ `fix/security-review` 上で作業する。main には直接コミットしない。
- 各フェーズの流れ: 計画を提示 → 承認後に実装 → `pytest` が全部通る → フェーズ単位でコミット。
- 見た目（CSS・テーマ・レイアウト）は変えない。挙動の修正だけに留める。
- Windows 専用モジュール（`win32com`, `os.startfile`）はテストでモックする。
- 対象は Windows 10/11、pywebview 6.1（Edge WebView2）。pywebview の API は推測で書かず、6.1 のドキュメントで確認する。
- 迷ったら実装を止めて質問する。

---

## Phase 0: テスト基盤の整備

**目的:** 以降のフェーズを安全に検証できるようにする。

- `tests/test_config.py` をプロジェクト直下ではなく `tmp_path` に書くように変更する（ConfigManager に絶対パスを渡す）。
- `test_edit_category` の `manager.update_shortcut = None` を削除する。
- 空の `tests/test_launcher.py` に最低限のテスト枠を作る。
- 開発用の依存を `requirements-dev.txt` に分離する（pytest, pip-audit など）。

**完了条件:** `pytest` 実行後、プロジェクト直下にファイルが残らない。

---

## Phase 1: 起動処理（src/core/launcher.py）

| # | 問題 | 修正方針 |
|---|------|----------|
| 1 | `.lnk` の引数・作業フォルダが捨てられる（Valorant が起動せず Riot Client が開く） | `.lnk` / `.url` / `.bat` は解析せず、元ファイルを `os.startfile()` で開く |
| 2 | `Popen(文字列)` で引数付き文字列が実行され、引用符なしパス問題（`C:\Program.exe`）も起きる | `.exe` は `Popen([path], cwd=dirname)` とリストで渡す |
| 3 | 管理者権限が必要な exe で WinError 740 | 740 のときは `os.startfile` にフォールバックする |
| 4 | URL の判定が大文字小文字を区別し、`http` 前方一致が緩い | `urllib.parse` でスキームを取り出し、許可リスト（`steam`, `riot`, `https`, `http`, `com.epicgames.launcher`）で判定する |
| 5 | `configparser` の `%` 展開で `.url` の解析に失敗し、文字コードも不統一 | `ConfigParser(interpolation=None)` と `encoding='utf-8'`、失敗時は `cp932` で再試行 |
| 6 | 起動前に存在チェックをしていない | ファイルが存在しなければ `False` を返し、原因をログに出す |

- 保存データの形式: ショートカットには **登録したファイルのパスをそのまま** 保存する（.lnk なら .lnk のパス）。表示用に解決先を別キー `target` として持つのは可。
- 既存の `settings.json` に入っている解決済みパスも、引き続き起動できること（後方互換）。

**テスト:** 拡張子別の分岐、スキーム許可リスト、存在しないパス、740 フォールバック（すべてモック）。

---

## Phase 2: API の入力検証（src/api.py）

**前提:** `js_api` に渡したクラスの公開メソッドは、すべて JS から呼べる。

- `load_settings` / `save_settings` / `self.settings` を削除する（未使用。起動時にクラッシュする原因で、JS から古いデータで上書きもできる）。
- 内部用のメソッドには `_` を付けて JS から呼べないようにする。
- `add_shortcut`: Python 側で次の検証を行う。
  - 実在するファイルであること。
  - 拡張子が `.exe .lnk .url .bat` のどれかであること。
  - UNC パス（`\\` で始まる）は拒否する。
  - 理想は、`select_file` / ドロップで得たパスを Python 側で一時的に記録し、記録にあるパスだけ受け付けること。
- `.url` の `IconFile` も UNC パスなら読まない（NTLM ハッシュ漏えい対策）。
- `update_setting`: キーと値を許可リストで検証する。
  - `theme`: `get_themes()` の結果に含まれる値のみ。
  - `language`: `ja` / `en` のみ。
  - `card_size`: `small` / `medium` のみ。
- `name` には長さ上限（例: 100文字）を設け、制御文字を除去する。
- `launch_app` の import 重複を解消する。

**テスト:** 不正な拡張子・UNC パス・存在しないパス・不正な設定キーが拒否されること。

---

## Phase 3: XSS 対策（src/ui/script.js）

- `innerHTML` + テンプレート文字列 + インライン `onclick` をやめる。
  - 要素は `createElement` + `textContent` + `addEventListener` で組み立てる。
- アイコンの `src` は `data:image/webp;base64,` で始まるものだけを許可する。
- 重複・不要コードを整理する。
  - `applyTheme` の二重定義。
  - `applySettings`（存在しない `get_settings` を呼んでいる）。
  - `pywebviewready` のリスナー2つ → 1つの初期化関数にまとめる。
- `loadAndApplySettings` の `const currentSize` への再代入を `let` に直す。
- `document.body.className = ...` の全上書きをやめる（テーマ切り替えは theme-link のみで行う）。

**確認:** `Assassin's Creed` や `a');alert(1);('` という名前で、表示・編集・削除が正常に動き、スクリプトが実行されないこと。

---

## Phase 4: 外部依存の同梱と CSP

- Sortable.js を `src/ui/vendor/` にローカル同梱する（バージョン固定、ライセンス表記も同梱）。
- Google Fonts をローカル同梱する（OFL ライセンス）か、システムフォントへのフォールバックを用意する。
- `index.html` に CSP の meta タグを追加する（`default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'` を基準にし、pywebview の動作に必要な最小限だけ緩める）。
- PyInstaller の設定で vendor フォルダが含まれることを確認する。

**完了条件:** ネットワークを切った状態でも、起動・描画・並べ替えができる。

---

## Phase 5: データ保護（src/core/config.py, api.py）

| # | 問題 | 修正方針 |
|---|------|----------|
| 1 | JSON が壊れているとデフォルト値が返り、次の保存で全データを上書き | 読み込み失敗時は「読み取り専用モード」にして保存を拒否し、UI に通知する。壊れたファイルは `settings.corrupt-日時.json` として退避する |
| 2 | 書き込みが原子的でない | 同じフォルダに一時ファイルを書き → `flush` + `os.fsync` → `os.replace` で差し替える |
| 3 | バックアップがない | 保存前に `settings.json.bak` を1世代残す。読み込み失敗時は `.bak` からの復元を試みる |
| 4 | `default_data` を参照のまま返している | `copy.deepcopy` してから返す |
| 5 | `save_order` が並び順に載っていない項目を消す | 並び順に無いカテゴリ・ショートカットは末尾に残す。重複 ID は無視する |
| 6 | 古い形式（`config` キーなし）で KeyError | 読み込み時にスキーマを補完する関数を通す |
| 7 | ConfigManager のパス解決が二重 | ConfigManager は常に絶対パスを受け取る設計に統一する（`settings.json.example` のパスも main.py 側で解決して渡す） |

**テスト:** 壊れた JSON、空ファイル、旧形式、並び順の欠落、書き込み途中の例外（モック）でデータが失われないこと。

---

## Phase 6: 使い勝手のバグ

- ドラッグ＆ドロップ: WebView2 には `file.path` が存在しない。pywebview 6.1 のドロップ時フルパス取得（`pywebviewFullPath`）に置き換える。追加は Phase 2 の検証を通すこと。
- Sortable の多重生成: `renderApp` のたびに `#app-container` へ作り直さない（初回のみ生成、または既存インスタンスを `destroy`）。
- `renderApp` の多重実行対策（実行中フラグ、または直列化）。
- 二重起動対策: 起動クリック後、約1秒はクリックを無効にする。
- 起動失敗時の `alert` を i18n 化する（`lang/*.json` にキーを追加）。
- アイコン生成元の名前が空文字のときに `item.name[0]` で落ちないようにする。
- `print` を `logging` に置き換え、EXE の隣（または `%LOCALAPPDATA%\PaletteLaunch\`）にログファイルを出力する（ローテーションあり）。
- アプリの二重起動防止（名前付きミューテックスなど）。

---

## Phase 7: お手入れ

- `src/core/init.py`（`__init__.py` の打ち間違い）を削除する。
- `docs/architecture.md` を現状のコードに合わせて更新する（フォント、main.py の役割、ConfigManager の位置づけ）。
- README の「名前をクリックすると編集」を、実際の操作（✎ボタン）に合わせて直す。
- `pip-audit -r requirements.txt` を実行し、結果に応じて依存を更新する。
- README に開発環境の手順を追記する（Python 3.12 / `py -3.12 -m venv .venv` / `pip install -r requirements-dev.txt` / `pytest`）。Phase 0 で `.python-version` を削除したため。
- `.gitattributes` を追加して改行コードを統一する（Phase 0 のコミット時に LF/CRLF の警告が出たため）。
