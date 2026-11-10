# PaletteLaunch

ゲームやアプリのショートカットをカテゴリーごとに並べて、ワンクリックで起動する Windows 用のランチャー。
テーマを切り替えて、好きな見た目で使える。

- 対応 OS: Windows 10 / 11（x64）。Microsoft Edge WebView2 ランタイムが必要（Windows 11 には標準で入っている）
- インストール不要。zip を展開して `PaletteLaunch.exe` を起動する
- ネットワークに接続しなくても動く（フォントなども同梱）

## 機能

- カテゴリーを作って、ショートカットを分けて並べる
- 登録できるもの: `.exe`、`.lnk`（ショートカット）、`.url`（Steam などのインターネットショートカット）、`.bat`
- アイコンと名前を自動で取得する
- ドラッグ＆ドロップでの登録と並べ替え
- テーマ 10 種類、言語（日本語 / English）、カードの大きさ（標準 / 小）の切り替え
- 設定の自動バックアップと、壊れたときの自動復元
- 二重起動の防止（起動済みのウィンドウを前面に出す）

## 使い方

### カテゴリーの作成・変更・削除

- 画面上部の **「+ カテゴリー」** をクリックし、カテゴリー名（例: Games, Work, Tools）を入力する。
- **名前を変える**: カテゴリー名をクリックする。
- **削除する**: カテゴリーの **「削除」** をクリックする（中のショートカットもすべて消える）。

### ショートカットの登録

- 登録したいカテゴリーの **「+ アプリ」** をクリックし、ファイルを選ぶ。
- 名前の確認が出るので、そのまま、または変えて OK を押す。アイコンは自動で取得される。
- `.lnk` は、ショートカットそのもの（引数や作業フォルダを含む）を登録する。
  リンク先が見つからない `.lnk`（ドライブを外した、ゲームを移動した など）は登録できない。
- ネットワーク上のファイル（`\\` で始まるパス）は登録できない。

### 起動・編集・削除

- **起動**: カードをクリックする（続けてクリックしても、約 1 秒は二重に起動しない）。
- **名前を変える**: カードにマウスを乗せると出る **✎** ボタンをクリックする。
- **削除する**: カードにマウスを乗せると出る **✕** ボタンをクリックする。

### ドラッグ＆ドロップ

- **登録**: エクスプローラーから `.exe` / `.lnk` / `.url` / `.bat` を、追加したい **カテゴリーの上**（見出しを含む）にドロップする。
  ドラッグ中は、ドロップ先のカテゴリーが点線の枠で示される。カテゴリーの外にドロップすると、理由が表示されて何も追加されない。
  うまく追加できないときは「+ アプリ」から登録する。
- **並べ替え**: ショートカットやカテゴリーをドラッグして並べ替える。順番は自動で保存される。

### テーマ・言語・大きさ

画面上部の選択欄で切り替える。設定はすぐに保存される。

- テーマ: Apex / Cyberpunk / Hydrangea（Blue / Pink / Purple を含む 4 種）/ MHW / Minecraft / Starry / Valorant
- 言語: 日本語 / English
- カードの大きさ: 標準（アイコン + 名前）/ 小（アイコンのみ）

## 設定のバックアップと復元

設定は `PaletteLaunch.exe` と同じフォルダの `settings.json` に保存される。同じフォルダに、バックアップが自動で作られる。

| ファイル | 内容 |
| --- | --- |
| `settings.json.bak` | 1 つ前の保存の状態 |
| `settings.YYYYMMDD.bak.json` | その日の最初の保存の直前の状態（7 日分） |
| `settings.corrupt-YYYYMMDD-HHMMSS.json` | 読めなかった `settings.json` のコピー（同じ内容は重複して作らない。10 個まで） |

- `settings.json` が壊れていたら、`settings.json.bak` から自動で復元する。復元できないときは **読み取り専用** で起動し、変更を保存しない（壊れたファイルを上書きしないため）。
- 日ごとのバックアップから戻す手順は [docs/backup.md](docs/backup.md) を参照。
- 新しいバージョンに上書き展開しても、`settings.json` は消えない（配布 zip に `settings.json` は入っていない）。

## ログ

`%LOCALAPPDATA%\PaletteLaunch\logs\palettelaunch.log`（1MB × 3 世代でローテーション）。
エクスプローラーのアドレス欄に `%LOCALAPPDATA%\PaletteLaunch\logs` と入力すると開ける。
起動やドロップがうまくいかないときは、このログを見る。

## 二重起動の防止

PaletteLaunch はユーザーごとに 1 つだけ起動する。すでに起動しているときにもう一度起動すると、
起動済みのウィンドウが前面に出て（最小化していれば元に戻る）、2 つ目はすぐに終了する。
前面に出せないときは、タスクバーのボタンが点滅する。

## v1.1.0 以前からの移行

1. 古い PaletteLaunch を終了する。
2. 新しい zip を、**古いものとは別のフォルダ**に展開する。
3. 古い `PaletteLaunch.exe` と同じフォルダにある `settings.json` を、新しい `PaletteLaunch.exe` と同じフォルダに **コピー** する
   （古い方は、念のためそのまま残しておく）。
4. 新しい `PaletteLaunch.exe` を起動する。カテゴリー・ショートカット・テーマなどがそのまま表示される。

- 古い形式の `settings.json` もそのまま読める。足りない項目は自動で補われ、最初に保存するときに元の内容が `settings.json.bak` と日ごとのバックアップに残る。
- **`.lnk` から登録したショートカット（VALORANT など）は、登録し直すことを勧める。**
  v1.1.0 以前は、`.lnk` のリンク先の exe だけを保存していたため、ショートカットの引数（`--launch-product=valorant` など）が失われ、
  ゲームではなく Riot Client などが開くことがある。いったん削除して、`.lnk` を「+ アプリ」かドラッグ＆ドロップで登録し直す。
- 以前の「大」サイズを使っていた場合は、「標準」で表示される。

## 開発

### 開発環境の準備（初回のみ）

Python 3.12（python.org のインストーラー版。`py -3.12` で起動できること）を使う。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

### 起動とテスト

```powershell
.venv\Scripts\python main.py      # 開発時の起動（settings.json はプロジェクト直下に作られる）
.venv\Scripts\python -m pytest    # テスト（本物の settings.json には触れない）
```

### 依存の脆弱性の確認

日本語の Windows では、そのまま実行すると requirements の日本語コメントを cp932 として読もうとして
`UnicodeDecodeError` になる。`PYTHONUTF8=1` を付けて実行する。

```powershell
$env:PYTHONUTF8 = '1'
.venv\Scripts\python -m pip_audit -r requirements.txt
.venv\Scripts\python -m pip_audit -r requirements-dev.txt
```

依存を更新するときは、公開から 2 週間以上たった版を選ぶ。pywebview は 6.1 に固定している
（理由と更新の手順は [docs/security-fix-plan.md](docs/security-fix-plan.md) の Phase 6「ドロップのパス検証」）。

### ドキュメント

- [docs/architecture.md](docs/architecture.md): 構成・データの流れ・実装の急所
- [docs/build.md](docs/build.md): ビルド・配布 zip の作成・起動確認の手順
- [docs/backup.md](docs/backup.md): 設定のバックアップと復元
- [docs/security-fix-plan.md](docs/security-fix-plan.md): セキュリティ・品質の修正計画と各 Phase の記録

## ライセンス

[LICENSE](LICENSE)（MIT）。同梱しているフォント（OFL）と Sortable.js（MIT）のライセンスは、
`src/ui/fonts/` と `src/ui/vendor/` にある。
