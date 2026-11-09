# 同梱フォント

すべて SIL Open Font License 1.1。各フォントのライセンス文書は `OFL-<フォント名>.txt`。

## 取得元

[google/fonts](https://github.com/google/fonts) のコミット
`5bb28733cec313b63fbd415b574b5ae35c8aa8b8` の `ofl/` 以下から取得（2026-11-09）。
取得時に、各ファイルの git blob SHA を GitHub API の値と照合済み。

| 同梱ファイル | 元ファイル | 加工 |
|---|---|---|
| `Orbitron-Variable.ttf` | `ofl/orbitron/Orbitron[wght].ttf` | なし（ファイル名のみ変更） |
| `Teko-Variable.ttf` | `ofl/teko/Teko[wght].ttf` | なし（ファイル名のみ変更） |
| `Silkscreen-Regular.ttf` | `ofl/silkscreen/Silkscreen-Regular.ttf` | なし |
| `Silkscreen-Bold.ttf` | `ofl/silkscreen/Silkscreen-Bold.ttf` | なし |
| `Cinzel-Variable.ttf` | `ofl/cinzel/Cinzel[wght].ttf` | なし（ファイル名のみ変更） |
| `Oswald-Variable.ttf` | `ofl/oswald/Oswald[wght].ttf` | なし（ファイル名のみ変更） |
| `NotoSansJP-Variable.woff2` | `ofl/notosansjp/NotoSansJP[wght].ttf` | WOFF2 に変換（サブセット化なし） |
| `ShipporiMincho-Regular.woff2` | `ofl/shipporimincho/ShipporiMincho-Regular.ttf` | WOFF2 に変換（サブセット化なし） |
| `ShipporiMincho-Bold.woff2` | `ofl/shipporimincho/ShipporiMincho-Bold.ttf` | WOFF2 に変換（サブセット化なし） |

WOFF2 への変換は fontTools 4.67.0 + brotli 1.2.1（`requirements-dev.txt`）で、
字形数と cmap が元の TTF と一致することを確認している。

```python
from fontTools.ttLib import TTFont
f = TTFont("NotoSansJP[wght].ttf")
f.flavor = "woff2"
f.save("NotoSansJP-Variable.woff2")
```

日本語フォントは、ショートカット名に任意の漢字が入るためサブセット化しない。

## SHA-256

### 元ファイル（変換前）

```
c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f  NotoSansJP[wght].ttf
769b5269f0f9bc6534b352c0e6bd856a566e03ff788f107191c2d835863570b2  ShipporiMincho-Regular.ttf
63bc4eddc74793f671c3ab827c5175e773ffbe569d0bf50ee65375ea9e3bc286  ShipporiMincho-Bold.ttf
```

### 同梱ファイル

```
f42db2dd16e642258e35782916eceb1dcdbea06fb958d77ad71dc5963587e8fd  Orbitron-Variable.ttf
d1321889f262bbbff632e7976349853399cd097b6f382d4b19790c915c13c1ae  Teko-Variable.ttf
c845473330b94c2079ce9af01c51ac8ba2d99c24f4d14c039843bbb8e642ebd8  Silkscreen-Regular.ttf
768476aa712d4f5c3e18d3bce80f980a8bd3f72b7094d22ec5e768df3acfed61  Silkscreen-Bold.ttf
f4d83d34d1f6c741193e4acf4b3dff9531e5a67b6aa65228d00a7db72a4e0f34  Cinzel-Variable.ttf
5b38c246e255a12f5712d640d56bcced0472466fc68983d2d0410ec0457c2817  Oswald-Variable.ttf
15a55c30c1d914f16b5249557e7b50c837d6cdf166dc01bb79738de0b5364c43  NotoSansJP-Variable.woff2
ed09da78b65bd05059e606f82df3a4ffea7daba00ba561f263328f689d5d5ab6  ShipporiMincho-Regular.woff2
9efdda041712f2dc77506542831755d6d8b008982c79b6e9860b2d0723971b79  ShipporiMincho-Bold.woff2
```

## 予約フォント名（Reserved Font Name）について

- Orbitron（RFN: "Orbitron"）は無加工で同梱している。
- Noto Sans JP（RFN: "Source"）は WOFF2 への形式変換のみで、"Source" の名前は使っていない。
- そのほかのフォントに RFN の指定はない。
