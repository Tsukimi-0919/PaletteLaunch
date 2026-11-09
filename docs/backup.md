# 設定のバックアップと復元

PaletteLaunch の設定（カテゴリー・ショートカット・テーマなど）は、`PaletteLaunch.exe` と同じフォルダの
`settings.json` に保存される。同じフォルダに、次のファイルが自動で作られる。

| ファイル | 内容 |
|---|---|
| `settings.json` | 今の設定 |
| `settings.json.bak` | 1つ前の保存の状態（保存のたびに更新） |
| `settings.YYYYMMDD.bak.json` | その日の最初の保存の直前の状態（例: `settings.20261109.bak.json`）。新しいものから 7 日分を残し、古いものは自動で削除する |
| `settings.corrupt-YYYYMMDD-HHMMSS.json` | 起動時に読めなかった `settings.json` のコピー（自動では削除しない） |

- 保存の直前のファイルが壊れているときは、`.bak` も日ごとのバックアップも作らない（正しいバックアップを壊れたもので上書きしないため）。
- バックアップの作成や削除に失敗しても、設定の保存は続ける。

## 起動時に settings.json が読めなかったとき

| 状態 | 動作 |
|---|---|
| 壊れている（JSON として読めない、形が違う） | `settings.corrupt-日時.json` にコピーしてから、`settings.json.bak` が正しければそこから自動で復元する。`.bak` も無い・壊れているときは**読み取り専用**で起動する |
| 空（0 バイト） | `settings.json.bak` があれば復元する。無ければ新しく作る |
| 他のアプリが開いている等で読めない | 読み取り専用で起動する |

読み取り専用のあいだは、どの変更も保存されない（`settings.json` はそのまま残る）。
下の手順でファイルを戻してから、アプリを起動し直すこと。

## 日ごとのバックアップから戻す手順

1. PaletteLaunch を終了する。
2. `PaletteLaunch.exe` のフォルダで、今の `settings.json` を別の名前に変えて残しておく（例: `settings.old.json`）。
3. 戻したい日の `settings.YYYYMMDD.bak.json` をコピーし、コピーしたファイルの名前を `settings.json` に変える。
4. PaletteLaunch を起動し、内容を確認する。

`settings.json.bak`（1つ前の保存）に戻すときも同じ手順で、手順 3 のファイルを `settings.json.bak` にする。

> 注意: ファイル名の変更は、エクスプローラーで拡張子を表示した状態（表示 → 表示 → ファイル名拡張子）で行うこと。
> `settings.json.json` のような名前になると読み込まれない。
