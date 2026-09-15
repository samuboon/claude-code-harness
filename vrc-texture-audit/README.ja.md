**English: [README.md](README.md)**

# vrc-texture-audit — 誰も使っていないアルファが、そのテクスチャの半分を食っている

全画素が不透明なのに RGBA で保存されたテクスチャは、BC1 ではなく BC3 で圧縮される。絵は同じで **VRAM は 2 倍**。Unity は教えてくれない。Unity から見れば、アルファ板を要求されて渡しただけだからである。

この道具はフォルダを歩き、ヘッダを読み、**PNG のアルファ板を実際に展開して**、アルファが死に荷物になっているファイルを名指しする。

```
$ python3 vrc_texture_audit.py ./Assets/MyAvatar --platform both

file                     fmt         size  alpha         est
Body/body_basecolor.png  png    4096x4096  UNUSED     21.33M
Body/body_normal.png     png    2048x2048  UNUSED      5.33M
Hair/hair_basecolor.png  png    2048x2048  yes         5.33M
Hair/hair_mask.png       png    1024x1024  UNUSED      1.33M
Hair/hair_mask_copy.png  png    1024x1024  UNUSED      1.33M
Body/eye_1000x600.png    png     1000x600  yes         0.76M *

6 textures, 35.43 MB estimated (1.2s)
  PC    -> Excellent (Excellent band is <= 40 MB; VRChat's own thresholds, read 2026-09-15)
  QUEST -> Poor (Poor band is <= 40 MB; VRChat's own thresholds, read 2026-09-15)

findings:
  [alpha not used] 4 texture(s) carry an alpha channel in which every pixel is opaque.
                   dropping the alpha frees an estimated 14.67 MB:
                     Body/body_basecolor.png (4096x4096, -10.67 MB)
                     ...
  [duplicate] 1 group(s) of byte-identical files, est 1.33 MB shipped twice:
                Hair/hair_mask.png == Hair/hair_mask_copy.png
  [not power of two] 1 texture(s), marked * above
```

**Unity 不要・Blender 不要・pip install 不要。**1 ファイル、Python 3.8 以上、標準ライブラリだけ、通信なし。**試験 59 本、わざと壊した 28 通りをすべて検出。**

---

## 使い方

```bash
python3 vrc_texture_audit.py ./Assets/MyAvatar
python3 vrc_texture_audit.py ./Assets/MyAvatar --platform quest --format md   # そのまま貼れる形
python3 vrc_texture_audit.py ./Assets/MyAvatar --max-mb 40                    # 超えたら終了コード 1
```

| オプション | 既定 | |
|---|---|---|
| `--platform` | `pc` | `pc` / `quest` / `both`。 |
| `--format` | `text` | `text` / `tsv`(表計算に貼る)/ `md`(issue や PR に貼る)。 |
| `--top` | `20` | 表示する行数。大きい順。`0` で全部。 |
| `--max-mb` | *(なし)* | 見積もりがこれを超えたら終了コード **1**。CI 用。 |
| `--no-alpha-scan` | off | ヘッダだけ読む。速いが、いちばん重い指摘が消える。 |
| `--max-scan-pixels` | `67108864` | これより大きい絵はアルファ展開を飛ばす(固まらせない)。飛ばした分は印を付け、「不透明」には数えない。 |

終了コード: **0** 点検した / **1** `--max-mb` 超過 / **2** 1 枚も読めなかった(打ち間違えたパスに「異常なし」を出してはいけない)。

読む拡張子は `.png` `.jpg` `.tga` `.bmp` `.psd` `.gif`。アルファの**展開**は PNG だけで、他はヘッダからアルファ板の有無を読む。

---

## 見つける 3 つ

**1. 全画素が不透明なアルファ板。**これのために作った。判定は「アルファ板があるか」ではない(書き出せばたいてい付く)。「その中に 255 でない画素が 1 つでもあるか」である。パレット PNG は `tRNS` だけで答え、RGBA とグレースケール+アルファは展開して答える。

**2. バイト単位で同一の重複。**同じマスクを 2 つの名前で書き出していれば、2 回積んで配っていることになる。

**3. 2 の冪でない寸法。**`*` を付ける。圧縮を止めるわけではないが、たいてい書き出しの事故である。

## 数字の出どころ

| 数字 | 出どころ |
|---|---|
| Texture Memory の閾値 | VRChat 自身の文書 [Avatar Performance Ranking System](https://docs.vrchat.com/docs/avatar-performance-ranking-system)(2026-09-15 に読んだ)。PC `40 / 75 / 110 / 150` MB、Quest `10 / 18 / 25 / 40` MB、順に Excellent / Good / Medium / Poor。Poor を超えたものが Very Poor。ここを書き換えると試験が落ちる。 |
| 1 枚あたりの MB | **こちらの算術であって、VRChat が表示する値ではない。**BC1 = 4x4 ブロック 8 バイト = 0.5 B/px、BC3 = 16 バイト = 1.0 B/px、ミップマップで 4/3 倍。 |
| アルファが分からないとき | **「ある」側に倒して**計上する。少なく見せる点検表は、多く見せる点検表より悪い。 |

## 4096x4096 の PNG を素の Python で展開できる理由

PNG のフィルタは**バイト単位**で、「左」の参照先は `bpp` バイト前 —— つまり 1 つ前の画素の同じ成分である。**したがって RGBA8 のアルファ板は、他の 3 成分と無関係に単独で復元できる。**展開した生バイトの 4 分の 3 を捨てられる。4096x4096 の RGBA PNG 1 枚での実測(Python 3.13.3・2026-09-15):

| | |
|---|---:|
| 4 成分すべてを復元 | 2.75 秒 |
| **アルファ板だけを復元** | **0.90 秒** |

さらに、不透明でないバイトが 1 つ出た時点で打ち切る。アルファを実際に使っているテクスチャはほぼ即答になる(2048x2048 の抜きあり: 0.019 秒)。

---

## この道具にできないこと

がっかりされる前に書いておく。

- **MB は見積もりで、VRChat の数字ではない。**VRChat の値はビルドされたアセットバンドルから出る。インポート設定が上の前提と違えば数字も違う。**テクスチャ同士を比べるために使い、アップローダの表示と論争するために使わない。**
- **Unity のインポート設定を読まない。**`Max Size`・`Compression`・`Crunch`・`Generate Mip Maps`・`sRGB` のどれも見ない。`Max Size 1024` で取り込んだ 4096 の原寸は、ここでは 4096 のまま = 4 倍大きく出る。
- **Quest は BC を使っていない。**ASTC である。0.5/1.0 B/px の算術はそこでは代用品にすぎず、Quest の判定行がこの道具のいちばん弱いところである。
- **アルファの展開は PNG だけ、しかも全 PNG ではない。**インターレースと 8/16 以外のビット深度は *unknown* と出す(「使っていない」とは絶対に言わない)。TGA・PSD・BMP・GIF はヘッダだけで、GIF の透過色は見ていない。
- **どのテクスチャがそのアバターで実際に使われているかを知らない。**フォルダを歩くだけである。使っていないファイルが入っていれば合計は膨らみ、外にあるテクスチャは見えない。
- **「アルファ未使用」は「アルファを消せ」ではない。**シェーダは smoothness・メタリック・各種マスクとしてアルファ板を読む。そこでは全面 255 が正しい値でありうる。**この道具は画素を報告するだけで、決めるのは使う人である。**
- **実際のアバター案件での実測がない。**当てた最大の木は 6 ファイルの検証用一式である。1,000 枚のフォルダには一度も向けていない。
- **PSD のレイヤは読まない。**ヘッダのチャンネル数だけを見るので、スポットチャンネルを持つ PSD がアルファ持ちと出ることがある。

## ファイル

| ファイル | |
|---|---|
| `vrc_texture_audit.py` | 本体。1 ファイル、標準ライブラリ以外を import しない。 |
| `test_vrc_texture_audit.py` | 試験 59 本。PNG の検体は本体と独立に書いた符号化側で組み立てている。`python3 test_vrc_texture_audit.py` |
| `mutation_check.py` | 本体を 28 通りにわざと壊し、試験が気付くか確かめる。`python3 mutation_check.py`。**誰も落ちるところを見たことがない試験は飾りである。**原本は `finally` で戻す。 |

出力は全部 ASCII にしてある(いちばん動く見込みが高いのが日本語 Windows のコンソールだから)。ソースのコメントは日本語。

[claude-code-harness](../README.ja.md) の一部。MIT。
