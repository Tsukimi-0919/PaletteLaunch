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

### Phase 1 の実機確認で見つかった追加項目

ドライブ移動などで .lnk のリンク先が存在しない場合、`os.startfile` で開くと Windows の「ショートカットの検索」ダイアログが出る。キャンセルすると WinError 1223 で失敗し、アイコンも取得できない。

- 登録時: .lnk の解決先が絶対パスのファイルで、かつ存在しない場合は登録を拒否し、「リンク先が見つかりません」と UI に返す（戻り値を True/False ではなく、理由が分かる形にする）。
- 起動時: 同じ条件のときは startfile を呼ばずに False を返し、ログに理由を出す（Windows のダイアログを出さない）。解決先が特殊なもの（シェルフォルダなど）で絶対パスでない場合は、従来どおり startfile に任せる。
- アイコン: .lnk はショートカットの IconLocation（「,0」などのインデックス付き）を最優先で読む。次に解決先の exe、最後に .lnk 自体の順で取得する。
- .url の IconFile が存在しない場合も、次の候補にフォールバックすること（現状どおり）。
- コンソールアプリ（例: `C:\Program Files\PowerShell\7\pwsh.exe`）を起動すると、新しいウィンドウが出ず、親プロセスのコンソールを使おうとする（`python main.py` で動かしていると起動しないように見える）。`.exe` の `Popen` に `creationflags=subprocess.CREATE_NEW_CONSOLE` を付ける。GUI アプリには影響しない。テストで creationflags が渡されることを確認する。

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

### Phase 6 の実施メモ（2026-11-09）

#### 透明なアイコン（実機で見つかった問題）

Steam の .url（例: OVR Advanced Settings, `steam://rungameid/1009850`）の `IconFile` が指す .ico には、
32×32 のフレームが 2 枚ある（32bpp の本物と、色データが 0・マスクがすべて透明の 1bpp の空フレーム）。
Pillow 11.3 は同じサイズのフレームを 1 枚しか使わず、空フレームを選ぶため、48×48 の完全に透明な WebP が保存されていた。

- `icons.py`: ICO（.ico と exe から取り出したもの）は全フレームを「大きいサイズ → 色深度が高い」の順に試し、
  透明でない最初のフレームを使う。すべて（またはほぼすべて: alpha ≥ 16 の画素が 1% 未満）透明なら失敗として `""` を返し、
  次の候補 → プレースホルダーの順に進む。
- `api.get_config`: 保存済みの透明なアイコンは、UI に返すときだけ `""` にする（保存データは書き換えない）。
- `.url` の `IconIndex` を読むようにした（exe/dll を指しているとき用）。

#### ドロップのパス検証（pywebview を更新する人へ）

**問題:** pywebview 6.1 では、フルパスは Python 側の DOM ハンドラーに渡る event の `files[i]['pywebviewFullPath']` でしか受け取れない。
`webview/util.py` は、ネイティブ側の記録とファイル名が一致したときだけ値を上書きし、一致しなければ JS から来た値を残す。
JS から次を呼ぶと、任意のパスをハンドラーに届けられる（2026-11-09 に WebView2 の実機で確認）。

```js
pywebview._jsApiCallback('pywebviewEventHandler',
  {event: {type: 'drop', dataTransfer: {files: [{name: 'x.exe', pywebviewFullPath: 'C:\\any\\x.exe'}]}},
   nodeId: 'document'}, 'eventHandler')
```

なお、作り物の `DragEvent` を `dispatchEvent` しても届かない。JS で作った `File` は、WebView2 が
`postMessageWithAdditionalObjects` で拒否する（"additional File object is not a file on the disk"）。

**対策（`src/core/drop_guard.py`）:** `webview.dom._dnd_state['paths']`（WebView2 のネイティブメッセージ `FilesDropped` からしか追加されない）を、
追加を記録するリストに差し替える。記録にあるパスだけを信頼する。記録は最後の 1 回のドロップ分だけを持ち、使ったら消し、30 秒で期限切れにする。
`add_shortcut` は、select_file で選んだパスか、照合できたドロップのパスしか受け付けない（Phase 2 の検証もすべて通す）。

**安全側に倒す:** pywebview が 6.1 以外、内部構造が違う、差し替えに失敗した — のどれかなら `DropGuard.enabled = False` になる。
その場合、drop ハンドラーは登録せず、ドロップでの追加は無効になる（ログに出る）。`requirements.txt` で `pywebview==6.1` に固定している。

**この仕組みを外してよい条件:** 新しい pywebview で次のどちらかをソースで確認し、`tests/test_drop_guard.py` の偽装テスト（方法 A）が新しい仕組みでも通ることを確かめる。
- JS から送られた `pywebviewFullPath` を必ず消す（または上書きする）ようになった。
- ネイティブ側で取得したパスを、JS を経由せずに受け取る公開 API ができた。

それまでは、pywebview を更新するとき、`drop_guard.EXPECTED_PYWEBVIEW_VERSION` と `requirements.txt` を一緒に更新する。
その前に、新しいバージョンの `util.py`（pywebviewEventHandler）と `platforms/edgechromium.py`（FilesDropped）が同じ仕組みのままであることを確認する。

#### ドロップしても追加されない問題（実機確認 2026-11-09）

**症状:** ログに「ネイティブの記録（FilesDropped）を受け取りました」だけが出て、何も追加されず、エラー表示も出なかった。

**原因（推定）:** pywebview の JS は、ドロップのたびに `FilesDropped`（`postMessageWithAdditionalObjects`）と DOM イベント（`postMessage`）を続けて送る。File を受け渡す前者の方が後に届くことがある。
その場合、pywebview はファイル名で照合できず、`pywebviewFullPath` が付かない。当時の `consume()` は記録が無いと**ログも出さずに**空を返し、JS にも知らせていなかった。
上の症状はこの順番とすべて一致するが、確定には実機のログ（下記）が必要。

**対策:**
- `DropGuard.consume()` は、記録が無ければ最大 2 秒（`NATIVE_WAIT_SECONDS`）待ち、届いた記録とファイル名で照合する。受け付けるパスは常に記録（ネイティブ側）の値。待っても届かなければ拒否する。
- 拒否したときは理由をログと UI の両方に出す。Python 側から 5 秒応答が無いときも、JS 側で理由を表示する。
- ドロップ先はカテゴリー全体（見出しを含む）にした。カテゴリーの外なら「カテゴリーの上にドロップしてください」と表示する。

**ログの見方（`%LOCALAPPDATA%\PaletteLaunch\logs\palettelaunch.log`）:** ドロップの流れの各段階に `[drop n/5]` を付けている。

| 段階 | ログ | 出るところ |
|---|---|---|
| 1 | `[drop 1/5] ネイティブの記録（FilesDropped）を受け取りました: n 件` | `drop_guard._record_native` |
| 2 | `[drop 2/5] DOM の drop ハンドラーが呼ばれました: n 件 …（pywebviewFullPath あり k 件）` | `API._handle_drop` |
| 3 | `[drop 3/5] ネイティブの記録がまだ無いため、最大 2.0 秒待ちます`（逆順のときだけ）、`[drop 3/5] 照合の結果: …`、拒否したときは理由の WARNING | `DropGuard.consume` |
| 4 | `[drop 4/5] JS に知らせます: 受け付け n 件、エラー …` | `API._handle_drop` |
| 5 | `[drop 5/5] JS がドロップの結果を受け取りました: …`、`[drop 5/5] add_shortcut の結果: … -> OK / エラーコード` | `API.add_dropped_shortcuts` |

1 と 2 の順番で、到着順が分かる（2 が先で 3 に「待ちます」が出れば逆順）。

#### 実機での確認が必要なこと

- エクスプローラーから .exe / .lnk / .url / .bat をカテゴリーにドロップして追加できること（.url は WebView2 がファイルとして渡さない可能性がある）。
- カテゴリーの外にドロップすると、理由が表示されて何も追加されないこと。
- 二重起動すると、起動済みのウィンドウが前面に出る（出せないときはタスクバーで点滅する）こと。

---

## Phase 7: お手入れ

- `src/core/init.py`（`__init__.py` の打ち間違い）を削除する。
- `docs/architecture.md` を現状のコードに合わせて更新する（フォント、main.py の役割、ConfigManager の位置づけ）。
- README の「名前をクリックすると編集」を、実際の操作（✎ボタン）に合わせて直す。
- `pip-audit -r requirements.txt` を実行し、結果に応じて依存を更新する。
- README に開発環境の手順を追記する（Python 3.12 / `py -3.12 -m venv .venv` / `pip install -r requirements-dev.txt` / `pytest`）。Phase 0 で `.python-version` を削除したため。
- `.gitattributes` を追加して改行コードを統一する（Phase 0 のコミット時に LF/CRLF の警告が出たため）。

---

## Phase 8: 見た目の調整（ユーザー報告 2026-11-09）

**この Phase だけは見た目を変える作業。** Phase 3・4 の「見た目を変えない」ルールの対象外とする。

### 報告された問題（v1.2.0、カードサイズ「小」で確認）

1. カテゴリー見出しの「＋アプリ」「削除」ボタンが、小サイズでは大きすぎる。カテゴリーの帯からはみ出す（Apex テーマで特に目立つ）。
2. ヘッダーの「＋カテゴリー」ボタンが、言語・テーマ・サイズの選択欄と高さや大きさがそろわず、一体感がない（ほとんどのテーマ）。
3. ヘッダーの選択欄どうしでも、高さや余白がそろっていないテーマがある。

### 進め方

1. **回帰かどうかを最初に確認する。** v1.1.0 のタグ（修正前）と現在の main で、全テーマ × 2 サイズのスクリーンショットを撮って比べる。
   - Phase 3・4 で変わっていた場合は、回帰として原因を特定し、まずそれを直す。
   - 前からの問題なら、デザインの改善として進める。
2. **方針を決めてから実装する。**
   - ヘッダーの操作部品（言語・テーマ・サイズの選択欄と「＋カテゴリー」）は、同じ高さ・同じ角丸・同じ文字サイズにそろえる。共通の CSS 変数（例: `--control-height`）で管理し、テーマ側は色や装飾だけを上書きする形を目指す。
   - カテゴリーの操作ボタンは、カテゴリーの帯の高さに収める。小サイズでは文字も余白も小さくする。
   - テーマごとの個性（Apex の太枠、Minecraft の立体枠、Valorant の斜めカットなど）は残す。
3. **確認方法。**
   - 全テーマ × 2 サイズの修正前後のスクリーンショットを並べた比較ページ（HTML）を作り、ユーザーが目で確認できるようにする。比較ページはリポジトリに入れない。
   - ヘッダーの部品の高さが、全テーマでそろっていることを数値（getBoundingClientRect）でも確認する。
   - ウィンドウ幅を狭くしたとき、ヘッダーが崩れないことも確認する。
