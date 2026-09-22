**English: [README.md](README.md)**

# pdf-text — 空文字列こそが不具合である

PDF が届いて、何かがそれを読まなければならない。poppler も入れられず `pip install` も通らない機械
——固められた実行環境、他人が組んだコンテナ——では、標準ライブラリ数百行で読むか、そもそも読まないか
の二択になる。

ここまでは既知の問題で、既知の答えがある。この道具が扱うのはその先である。

**走査した紙の頁と、文字の頁は、呼び出し側から見ると同じ物体である。**どちらも解析でき、どちらも頁を
持ち、どちらも例外を出さずに返ってくる。片方には文字が 1 つも入っていない。読み取り器がそれに `""`
で答えたなら、**「この文書は何も言っていない」と「この文書は写真である」の区別は、それが見えていた
唯一の場所で捨てられている。**下流へ流れていくのは、無の要約か、空欄か、初めから存在しなかった数字
である。

一段下に同じ形がある。`/ToUnicode` CMap を持たないサブセットフォントは、字形に私的な番号を振っている。
対応表に無いコードを黙って捨てる読み取り器は、**3,200 を 320 にして**、他の行と同じ顔で出力する。
**間違った数字は、欠けた数字より下流のあらゆる検査に強い。**欠けていれば誰かが問い合わせるからだ。

だからこの道具は、出口をすべて名指しする。

```
$ python pdf_text.py demo/scanned.pdf -o out.txt
file        demo/scanned.pdf
status      unreadable
pages       1
characters  0 (0 undecoded, 0.0%)
images      1

this PDF has 1 image and no text-drawing operators at all: the pages are pictures.
Text can only come out of it through OCR, which is not done here
$ echo $?
2
```

```
$ python pdf_text.py demo/glyph-ids.pdf -o out.txt
file        demo/glyph-ids.pdf
status      unreadable
pages       1
characters  7 (7 undecoded, 100.0%)
written     out.txt (UTF-8)

every character position was reached and none of them could be decoded

font ABCDEF+KozMinPr6N-Regular (object 5, /Type0) could not be decoded: it is a
composite (Type0) font with no /ToUnicode CMap, so its codes are glyph indexes into
a subset with no character meaning
$ echo $?
2
```

```
$ python pdf_text.py demo/cid-japanese.pdf -o out.txt
file        demo/cid-japanese.pdf
status      ok
pages       1
characters  28 (0 undecoded, 0.0%)
written     out.txt (UTF-8)
$ echo $?
0
```

**一部だけ読めた場合は、失敗ではなく「一部」として扱う。**読めた側はファイルに書き、読めなかった位置は
`U+FFFD` として出力に残し、その割合と原因のフォント名を報告に出す。

```
status      partial
characters  27 (2 undecoded, 7.4%)

7.4% of the characters could not be decoded (2 of 27). They are U+FFFD in the output;
any number on a line containing one may have lost a digit

font XXXXXX+Ghost (object 6, /Type0) could not be decoded: ...
```

終了コード **0 = 読めた** / **1 = 読めたが未復号が多すぎる**(`--max-missing`、既定 2%)/
**2 = 何も読めず、理由を名指しした** / **3 = 実行できなかった**。

---

## 読めるもの

- `FlateDecode` または無圧縮の内容ストリームの中の `Tj` / `TJ` で描かれた文字
- **`/ToUnicode` CMap を持つ CID(合成)フォント** —— 日本語の場合であり、この道具が存在する理由。
  `bfchar` と `bfrange` の 2 形式に対応
- 単純フォント(`/Type1` `/TrueType` `/MMType1` `/Type3`)を WinAnsiEncoding で。
  `/Differences` は数字・記号・`uniXXXX` 名に適用する
- オブジェクトを `/ObjStm` に畳んだ PDF 1.5 以降のファイル
- `ASCIIHexDecode`、およびフィルタの無いストリーム

## 読めないもの —— そして、そう言う

| 入力 | 返るもの |
|---|---|
| 走査した画像だけの頁 | 終了 2。画像の枚数と「OCR でしか取り出せない」 |
| `/ToUnicode` の無いサブセットフォント | 終了 2(または `partial`)。**BaseFont 名**と、そのコードに文字としての意味が無い理由 |
| 暗号化された PDF(`/Encrypt`) | 終了 2、名指し。**復号は一切試みない**(空のオーナーパスワードでも) |
| `LZWDecode` `ASCII85Decode` `RunLengthDecode` `Crypt` | フィルタ名を出し、そのストリームは出力に入れない(推測で埋めない) |
| PDF でないファイル | 終了 3、名指し |
| フォントの対応表に無いコード | 出力に `U+FFFD` を 1 文字。数え上げる。**決して捨てない** |

OCR・復号・レイアウト・読み順・段組み・表・フォーム・注釈は**やらない**。`TJ` の字送り量から語間
空白を復元することもしない。改行は `Td` / `TD` / `T*` から作る近似である。**ここでは意味を読んでいない。
文字を読んでいる。**忠実なレイアウトが要るなら本物の PDF ライブラリを入れるべきで、これは
**それができない機械のためのもの**である。

## 出力は必ずファイルへ、UTF-8 で

既定では本文を `<名前>.txt`(または `-o`)へ UTF-8 で書き、**標準出力には出さない**。cp932 の端末では
`print(日本語)` が `UnicodeEncodeError` を投げる —— 文書は読めていて、仕事は終わっていて、結果だけが
画面へ行く途中で死ぬ。`--stdout` は用意してあり、その場合は先に符号を張り替える。

同じ理由で、**この道具が自分について出す行はすべて ASCII に落としてある**(BaseFont 名もファイルパスも)。
自分の句読点で転ぶ報告は、報告が無いより悪い。(その失敗そのものを扱う道具がこの木にある:
[`print-codec/`](../print-codec/))

---

## 実測

**道具になった日(2026-09-23)。**ある提供元の説明頁がこちらに `403` を返し、その説明を拒んでいる当の
契約書 PDF は何事もなく配られていた。必要な欄は PDF の側にあった。作業環境には poppler が無く、入れる
手段も無かった。最初の版 —— `zlib` と `re` と `Tj` 演算子 —— は契約書を返し、**面白い半分が現れたのは
数字を原文と突き合わせたときだった**: **同じ読み取り器の以前の版は、対応表に無いコードを黙って捨てて
いた。**それで補助金の公募要領から作った出力は、金額から桁が落ちたまま、まったく正常に見えていた。
`""` にも `320` にも、見に行けと告げるものは何も無い。

だからここでの規律は、**読み取り器は失敗してよいが、黙っていてはならない**である。`U+FFFD` を出力に
書いて数え、`--max-missing` が悪い比率を非零の終了コードに変え、**読めない PDF 2 本をリポジトリに
置いて、名指しで落ちる経路が毎回のテストで実行されるようにしてある**。

**テストを信じる前に、わざと 6 通り壊した(2026-09-23)。**一度も落ちるところを見ていないテストは、
球の入っていない青信号である。以下をそれぞれ複製の側のソースに入れ、テストを流した。

| 壊した内容 | 捕まえたテスト数 |
|---|---|
| 未復号のコードを `U+FFFD` にせず捨てる | 4 |
| 読めないフォントを名指ししない | 2 |
| 画像だけの PDF を理由なしで返す | 1 |
| 出力ファイルを UTF-8 でなく cp932 で書く | 2 |
| 報告を ASCII に落とさない | 1 |
| `/Encrypt` を素通りさせて平文として読む | 1 |

**測っていないこと。**デモの PDF は `make_demo_pdfs.py` が書いたもので、野に在る PDF を集めた標本では
ない。各場合の**きれいな例**であって、実際の PDF の分布ではない。実文書に当てたのは少数(日本語の契約書
と公募要領)で、コーパスでは試していない。ここが想定していない形で出力する生成元は在ると考えてよい。

---

## ファイル

```
pdf_text.py         読み取り器と CLI
test_pdf_text.py    18 件のテスト(標準ライブラリのみ)
make_demo_pdfs.py   デモ PDF 4 本を一から書き出す
demo/text.pdf           単純フォント・数字        -> 終了 0
demo/cid-japanese.pdf   CID フォント + /ToUnicode -> 終了 0
demo/scanned.pdf        画像 1 枚・文字なし       -> 終了 2、名指し
demo/glyph-ids.pdf      サブセット・/ToUnicode 無 -> 終了 2、名指し
```

```
python make_demo_pdfs.py
python -m unittest test_pdf_text -v
```

Python 3.8 以上。標準ライブラリのみ。ライセンスはこのリポジトリと同じ MIT。
