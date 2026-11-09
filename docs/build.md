# ビルド手順（PyInstaller / onedir）

## 前提

- Windows 10 / 11（x64）
- Python 3.12（python.org のインストーラー版。`py -3.12` で起動できること）
- Microsoft Edge WebView2 ランタイム（Windows 11 には標準で入っている）

## 1. 開発環境の準備（初回のみ）

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## 2. バージョン番号

バージョンは **`src\version.py` の `__version__` だけ**で管理する。

```python
__version__ = "1.2.0"
```

リリースの流れ:

1. `src\version.py` を更新してコミットする。
2. 同じ番号の git タグを付ける（例: `git tag v1.2.0`）。
3. 下の `build.ps1` で zip を作る。

`build.ps1` は、コミットされていない変更があるときや、タグ `v<version>` が HEAD 以外を指しているときに警告を出す（ビルドは止めない）。

## 3. ビルドと zip 作成（build.ps1）

テスト → ビルド → zip 作成 → zip の検査までを 1 コマンドで行う。

```powershell
.\build.ps1
```

実行ポリシーで止められる場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

Windows PowerShell 5.1 と PowerShell 7 のどちらでも動く。

| オプション | 内容 |
|---|---|
| （なし） | pytest → PyInstaller → zip 作成 → zip の検査 |
| `-SkipTests` | pytest を省略する（通常は使わない） |
| `-SkipBuild` | テストとビルドを省略し、既存の `dist\PaletteLaunch\` から zip だけ作り直す |

出力:

| パス | 内容 |
|---|---|
| `dist\PaletteLaunch\` | ビルド結果（onedir） |
| `dist\PaletteLaunch-v<version>-win64.zip` | 配布用 zip（例: `PaletteLaunch-v1.2.0-win64.zip`） |

- zip を展開すると `PaletteLaunch\` フォルダが出てくる。
- **zip には `settings.json` とそのバックアップ類（`settings.json.bak`、`settings.*.bak.json`、`settings.corrupt-*.json`、保存途中の `settings.json.*.tmp`）を含めない**（docs/backup.md）。
  利用者が上書き展開しても設定が消えないようにするため。`dist\PaletteLaunch\` に `settings.json` があっても
  削除はせず、除外したコピー（`build\package\`、作成後に削除）から zip を作る。
- 最後に zip の中身を検査し（必須ファイルがあること・`settings.json` 類が無いこと）、サイズと SHA-256 を表示する。
- 失敗したときは終了コード 1 で止まる。

> **注意:** PyInstaller はビルドのたびに `dist\PaletteLaunch\` を作り直す。起動確認で `dist\PaletteLaunch\` に
> 作られた `settings.json` も消えるので、残したい設定はそこに置かないこと。

### 参考: 手動でビルドする場合

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\pyinstaller PaletteLaunch.spec --clean --noconfirm
```

出力は `dist\PaletteLaunch\`（`build\` と `dist\` は git 管理外）。

```
dist\PaletteLaunch\
├─ PaletteLaunch.exe
└─ _internal\
   ├─ settings.json.example
   ├─ src\ui\        … index.html / script.js / style.css / themes / lang / vendor / fonts
   └─ webview\ …    … pywebview と WebView2 の DLL
```

配布は `build.ps1` が作る zip で行う（手動の場合は `dist\PaletteLaunch\` フォルダごと、exe だけでなく
`_internal` も渡す。`settings.json` は含めないこと）。
`settings.json` は初回起動時に exe と同じフォルダに作られる。

## 4. 起動確認（ビルドのたびに実施）

配布物そのものを確認するため、**zip を別のフォルダに展開して**確認する
（`dist\PaletteLaunch\` で直接起動すると、そこに作られた `settings.json` が次のビルドで消える）。

### 4-1. zip の展開と同梱ファイルの確認

```powershell
$v = '1.2.0'   # src\version.py のバージョン
Expand-Archive dist\PaletteLaunch-v$v-win64.zip -DestinationPath $env:TEMP\pl-check -Force
dir $env:TEMP\pl-check\PaletteLaunch
dir $env:TEMP\pl-check\PaletteLaunch\_internal\src\ui\vendor
dir $env:TEMP\pl-check\PaletteLaunch\_internal\src\ui\fonts
```

- `PaletteLaunch\` に `PaletteLaunch.exe` と `_internal\` があり、**`settings.json` が無い**。
- `vendor\` に `Sortable.min.js` と `Sortable.LICENSE` がある。
- `fonts\` に `fonts.css`、フォントファイル（.ttf / .woff2）、`OFL-*.txt` がある。

### 4-2. オフラインでの起動（完了条件）

1. **ネットワークを切る**（Wi-Fi オフ / LAN ケーブルを抜く / 機内モード）。
2. 展開した `PaletteLaunch\PaletteLaunch.exe` をダブルクリックで起動する
   （初回起動で `settings.json.example` から `settings.json` が作られ、サンプルカテゴリーが表示される）。
3. 次を確認する。

| 確認項目 | 期待する結果 |
|---|---|
| 起動 | コンソール窓は出ず、ランチャーのウィンドウだけが開く |
| 描画 | カテゴリー・ショートカットが表示される |
| フォント | Valorant テーマで見出しが Orbitron（角ばった英字）、日本語が Noto Sans JP で表示される。Hydrangea 系テーマで日本語が明朝体（Shippori Mincho）になる |
| テーマ | テーマを切り替えると、配色とセレクトボックスの見た目が変わる |
| 並べ替え | ショートカットとカテゴリーをドラッグで並べ替えでき、再起動しても順番が保たれる |
| 追加 | 「+ アプリ」から .exe / .lnk を追加できる |
| 起動 | 追加したショートカットをクリックするとアプリが起動する |
| 文字選択 | 画面の文字をドラッグしても選択状態にならない |

4. 確認が終わったらネットワークを戻す。

### 4-3. 上書き展開で設定が残ることの確認

1. 4-2 でカテゴリーを追加するなど設定を変えてから、アプリを閉じる。
2. 同じ zip を同じ場所にもう一度展開する（上書き）。

   ```powershell
   Expand-Archive dist\PaletteLaunch-v$v-win64.zip -DestinationPath $env:TEMP\pl-check -Force
   ```

3. 再び起動し、1 で変えた設定がそのまま残っていることを確認する。
4. 確認が終わったら `$env:TEMP\pl-check` を削除する。

### 4-4. うまく動かないとき

- 画面が真っ白: `_internal\src\ui\index.html` があるか確認する。
- フォントが標準のゴシック体になる: `_internal\src\ui\fonts\` と `fonts.css` があるか確認する。
- 並べ替えができない: `_internal\src\ui\vendor\Sortable.min.js` があるか確認する。
- ログは `%LOCALAPPDATA%\PaletteLaunch\logs\palettelaunch.log` に出る（EXE の隣ではない）。
- 起動しない（すぐ終わる）: すでに起動している PaletteLaunch があると、そのウィンドウを前面に出して終了する。
  タスクバーや通知領域に残っていないか確認する。ログの `[instance]` の行に、ウィンドウを探した結果が出る。
  記録は `%LOCALAPPDATA%\PaletteLaunch\instance.json`（終了時に消える）。
- ファイルをドロップしても追加されない: ログに「ドロップの検証が無効」と出ていれば、pywebview の
  バージョンが確認済みのもの（6.1）と違う。`docs/security-fix-plan.md` の Phase 6 を参照。
- 原因を調べるときは、`main.py` の `webview.start(debug=False)` を一時的に `debug=True` にして
  `python main.py` で起動し、開発者ツールのコンソールに CSP 違反などのエラーが出ていないか確認する
  （`debug=True` のままビルド・配布しないこと）。

## 参考: 同梱物の更新

- Sortable.js: `src/ui/vendor/README.md`
- フォント: `src/ui/fonts/README.md`
- CSP: `src/ui/index.html` の meta タグとコメント（pywebview を更新したら、`webview/js/customize.js` の
  `disableTextCss` が変わっていないか確認し、変わっていたら style-src のハッシュを更新する）
