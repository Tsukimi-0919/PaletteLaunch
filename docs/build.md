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

## 2. テスト

```powershell
.venv\Scripts\python -m pytest
```

すべて成功することを確認してからビルドする。

## 3. ビルド

```powershell
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

配布するときは `dist\PaletteLaunch\` フォルダごと（exe だけでなく `_internal` も）渡す。
`settings.json` は初回起動時に exe と同じフォルダに作られる。

## 4. 起動確認（ビルドのたびに実施）

### 4-1. 同梱ファイルの確認

```powershell
dir dist\PaletteLaunch\_internal\src\ui\vendor
dir dist\PaletteLaunch\_internal\src\ui\fonts
dir dist\PaletteLaunch\_internal\settings.json.example
```

- `vendor\Sortable.min.js` と `Sortable.LICENSE` がある。
- `fonts\` に `fonts.css`、フォントファイル（.ttf / .woff2）、`OFL-*.txt` がある。

### 4-2. オフラインでの起動（完了条件）

1. 既存の `settings.json` を使いたくない場合は、`dist\PaletteLaunch\` に `settings.json` が無い状態にする
   （初回起動で `settings.json.example` から作られる）。
2. **ネットワークを切る**（Wi-Fi オフ / LAN ケーブルを抜く / 機内モード）。
3. `dist\PaletteLaunch\PaletteLaunch.exe` をダブルクリックで起動する。
4. 次を確認する。

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

5. 確認が終わったらネットワークを戻す。

### 4-3. うまく動かないとき

- 画面が真っ白: `_internal\src\ui\index.html` があるか確認する。
- フォントが標準のゴシック体になる: `_internal\src\ui\fonts\` と `fonts.css` があるか確認する。
- 並べ替えができない: `_internal\src\ui\vendor\Sortable.min.js` があるか確認する。
- 原因を調べるときは、`main.py` の `webview.start(debug=False)` を一時的に `debug=True` にして
  `python main.py` で起動し、開発者ツールのコンソールに CSP 違反などのエラーが出ていないか確認する
  （`debug=True` のままビルド・配布しないこと）。

## 参考: 同梱物の更新

- Sortable.js: `src/ui/vendor/README.md`
- フォント: `src/ui/fonts/README.md`
- CSP: `src/ui/index.html` の meta タグとコメント（pywebview を更新したら、`webview/js/customize.js` の
  `disableTextCss` が変わっていないか確認し、変わっていたら style-src のハッシュを更新する）
