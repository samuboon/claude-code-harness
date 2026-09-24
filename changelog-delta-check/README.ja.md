**English: [README.md](README.md)**

# changelog-delta-check —— rack の変更履歴では 2.2.9 が 2.2.8 の 4 か月前に出ている。RubyGems では 1 年後だ

`rack/rack` の CHANGELOG.md には、2.2.8 が 2023-07-31、2.2.9 が 2023-03-21 と書かれています。
RubyGems に 2.2.9 が載ったのは 2024-03-21 で、年が 1 つずれています。`rust-lang/mdBook` の 0.2.3 も
同じずれ方をしています(2018-01-18 と書いてあり、crates.io では 2019-01-18)。Textual の `[7.0.0]` の
リンクは `v6.11.0` から比べているので、開くと 6.12.0 の差分まで混ざります。PyPI を見ると 6.12.0 は
その前日に出ています。Flutter の 3.19.3 の見出しは、3.16.3 のリリースのページにつながっています。

どれも、その 1 行だけを見ても分かりません。`2023-03-21` は日付として正しく、`v6.11.0...v7.0.0` も
開ける URL です。ばれるのは**隣の項目と並べたとき**です —— 新しい版が下の古い版より前の日付に
なっている、比較のリンクが下の項目より手前から始まっている。

臨床検査室も同じやり方をしています。検査室は結果を 1 件ずつ人の目で確かめ直すことはしません。
同じ患者の前回の値と比べ、体では起こりえない差が出たら、検体の取り違えを疑って報告を止めます
(デルタチェック)。測れない検体は「不適」として返し、値を推測しません。`changelog_check.py` は
変更履歴にこれを当てます。リリースの項目を 1 つずつ(版・日付・リンク)読み、それぞれを隣と比べます。
どちらとも読める日付(`03/04/2024`)は「読めなかった」と数えて、使いません。

```bash
python changelog_check.py path/to/repo              # 木の中の CHANGELOG*・CHANGES*・HISTORY*・NEWS*・RELEASES*
python changelog_check.py CHANGELOG.md              # 1 ファイルだけ
python changelog_check.py . --as-of 2024-01-15      # 「今日」とみなす日(既定は今日)
python changelog_check.py . --explain               # 読んだリリースの項目も全部並べる
python changelog_check.py . --json                  # 指摘を JSON で
```

2026-09-24 に取った `rack/rack`・`Textualize/textual`・`flutter/flutter` の写しで:

```
$ python changelog_check.py rack
CHANGELOG.md:672: error DATE 2.2.9 is dated 2023-03-21, before 2.2.8 (2023-07-31) in the same release line
1 changelogs, 135 release entries read (135 dated, 0 undated); 3 dates out of order across release lines not reported (backports?); 1 errors, 0 warnings

$ python changelog_check.py textual
CHANGELOG.md:222: warning LINKDEF [6.12.0] has no link definition (it shows as plain text)
CHANGELOG.md:443: error DATE 5.1.1 is dated 2025-07-21, before 5.1.0 (2025-07-31) in the same release line
CHANGELOG.md:1145: warning LINKDEF [0.79.1] has no link definition (it shows as plain text)
CHANGELOG.md:1612: warning LINKDEF [0.56.4] has no link definition (it shows as plain text)
CHANGELOG.md:2898: error DUPVER 0.15.0 has a second entry (first at line 2891)
CHANGELOG.md:3501: error LINK [7.0.0] for 7.0.0 compares from v6.11.0, but 6.12.0 (2026-01-02) came out in between
CHANGELOG.md:3561: error LINK [0.80.0] for 0.80.0 compares from v0.79.0, but 0.79.1 (2024-08-31) came out in between
CHANGELOG.md:3598: error LINK [0.57.0] for 0.57.0 compares from v0.56.3, but 0.56.4 (2024-04-09) came out in between
1 changelogs, 226 release entries read (223 dated, 3 undated); 1 dates out of order across release lines not reported (backports?); 5 errors, 3 warnings

$ python changelog_check.py flutter
CHANGELOG.md:548: error LINK the heading's link for 3.19.3 points at the tag 3.16.3
CHANGELOG.md:848: error LINK the heading's link for 3.3.7 points at the tag 3.3.6
1 changelogs, 175 release entries read (107 dated, 68 undated); 2 errors, 0 warnings
```

(PyPI では Textual 5.1.1 は 5.1.0 と同じ 2025-07-31 に出ていて、21 のほうが打ち間違いです。3 つの
`LINKDEF` は、`[7.0.0]`・`[0.80.0]`・`[0.57.0]` のリンクが飛ばした 3 つのリリースで、その見出しにも
リンクがありません。)

標準ライブラリのみ。ファイルを読むだけで、何も実行せず、何も書かず、通信もしません(GitHub から
読むのは下の `replay_fixes.py` だけです)。最後の行は、読んだ変更履歴と項目の数を必ず言います。
見分けられる変更履歴が 1 本も無い木は、黙って合格にせず、そう書いて 2 で終わります。

---

## 何を報告するか

| 記号 | 段 | 意味 |
|---|---|---|
| `DATE` | error | 同じリリースの系統(major.minor が同じ)の中で、新しい版が古い版より前の日付になっている。どちらかの日付を 1 年ずらすと順番どおりになるときは「… in 2019 would fit」と添える |
| `DATE` | error | ある項目の日付が、上下の項目の日付の外にあり、1 年どちらかにずらすと間に収まる。いちばん新しい項目の「上」は今日。隣はファイルの中の位置で決める |
| `DATE?` | warning | 同じ形だが、日付が後のほうが古い系統のパッチ(4.1.0 の下の 4.0.1)のとき。版の順に並べた後追いの修正版(バックポート)は、新しい版より後の日付になって当然だから。Sinatra の 4.0.1 がこれ(RubyGems では 2025-05-23、変更履歴の日付の前日) |
| `FUTURE` | error | 今日(`--as-of`)より 2 日を超えて先の日付。いちばん新しい項目は 60 日を超えたら |
| `FUTURE?` | warning | いちばん新しい項目が 3〜60 日先: 予定の日付か |
| `BADDATE` | error | 暦に無い日付(`2024-02-30`、`2024-13-01`) |
| `DUPVER` | error | 1 つの版に項目が 2 つ。`1.3` と `1.3 beta3`、`2.0.2` と `2.0.2 Enterprise`、`13.0.1` と `13.0.1+security-01` は別のリリースとして扱い、`## 1.9.0` の下の `### 1.9.0 Changes` という小見出しは項目に数えない |
| `ORDER` | error | 同じ系統の中で、新しい順のファイルなのに正式版が後の版より上にある(`1.2.4` の上に `1.2.3`)。古い順のファイルなら逆。ファイルがどちら向きかは数えて決め、決めつけない。予告版(プレリリース)は正式版と順番を比べない(日付順のファイルでは混ざって並ぶため) |
| `LINK` | error | 比較のリンク(`[1.2.0]: …/compare/v1.1.0...v1.2.0`、または `## [1.2.0](…)` という見出しのリンク)の行き先がこの版でない / 起点がこの版より古くない / 起点が、ファイルの上でこの版以前の日付を持つ正式版を飛ばしている(Textual の `[7.0.0]` が 6.12.0 を越えて `v6.11.0` から)。飛ばしたのが予告版だけのとき、この版より後の日付の版だけのとき(Composer の `[2.10.0-RC1]` が `2.9.5` から: 2.9.6〜2.9.8 は RC の後に出た)は報告しない。タグへのリンク(`…/releases/tag/v1.2.0`、`…/tree/v1.2.0`)が別の版を指している。`[Unreleased]` のリンクが、いちばん新しいリリースより古い版から比べている(`TBD` の項目はリリースに数えない) |
| `LINKDEF` | warning | `## [1.2.0]` に `[1.2.0]:` の定義が無い(ほかの版にはリンクを定義しているファイルで)。画面には `[1.2.0]` という文字のまま出る。どの版にもリンクを付けないファイルには言わない |
| `DUPLINK` | warning | 版のリンクが、別の URL で 2 回定義されている。Markdown は最初のほうを使う |
| `PLACEHOLDER` | warning | 日付の入ったリリースより下で、まだ `YYYY-MM-DD`・`TBD` などのままになっている |

**リリースの項目として読むもの:** Markdown の `#` 見出し、下線を引く見出し(setext と
reStructuredText。コードの囲みと HTML のコメントの中は読まない)、見出しの無いファイルでは行頭の
`1.2.3 (2024-01-05)`。版は見出しの中の最初の「点でつないだ数」で、前に名前(`pkg@`・`pkg-v`・
`Version`・`Release`)があってよく、名前の違う項目(`pkg-a@2.0.0` と `pkg-b@1.0.5`)は同じ名前の
項目とだけ比べる。`2013.08.21, Version 0.11.7` は日付、そのあと版として読む。その系統の 3 桁の
リリース(`## 4.4.1`・`## 4.4.0`)の上にある 2 桁の見出し(`## 4.4`)は、リリースではなく節とみなす。
版「について」の見出し(`Upgrading from 1.9 to 2.0`、`Migrating from …`)は読み飛ばす。

**日付:** `2024-01-05`・`2024/01/05`・`2024.01.05`・`5 January 2024`・`January 5th, 2024`・
`Jan. 5, 2024`・`25/12/2023`・`12/25/2023`・`January 2024`(月だけ。日で比べない)を、見出しの中か、
そのすぐ下の行(`_Released 2024-05-01_`、または日付だけの行)から読む。`03/04/2024` はどちらとも
読めるので読まない —— 同じファイルの同じ区切りの日付に、日が先としか読めないもの(または月が先と
しか読めないもの)があるとき、区切りが点のときは、それに従う。

**終了コード:** 0 = error なし(warning で落ちるのは `--strict` のときだけ)/ 1 = error あり /
2 = リリースの項目のある変更履歴が見つからない。`node_modules`・`vendor`・`third_party`・`dist`・
`build`・`target`・`fixtures`・`testdata` と、点で始まるフォルダは探さない。

### CI で

```yaml
# .github/workflows/changelog.yml
on: pull_request
jobs:
  changelog:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: curl -fsSLO https://raw.githubusercontent.com/samuboon/claude-code-harness/main/changelog-delta-check/changelog_check.py
      - run: python3 changelog_check.py .
```

私たちは GitHub の上でこれを走らせていません(`.github/workflows/` ではなくここに置いているのは、
このフォルダを公開する鍵にワークフローの権限が無いからです)。

---

## 測ったこと

### 変更履歴を直したコミットの再生(`replay_fixes.py`)

直すときに人が使う言葉 —— "fix changelog date"・"changelog wrong year"・"fix compare links
changelog"・"fix unreleased link"・"changelog version typo" など 18 通り —— で GitHub のコミット検索を
引くと 1,343 本が出ました。**そのうち、コミットの差分そのものが(検査を走らせる前に読んで)、
版を変えずにリリースの見出しの日付を変えている / 日付を変えずに版を変えている / 版のリンクの URL を
変えている 313 本を残しました**(`replay_fixes.py --classify`)。それぞれについて、コミットの直前と
コミットの時点の変更履歴に検査を掛けました。「今日」はそのコミットの日付です。直前のファイルは、
raw.githubusercontent.com から読んだコミット後のファイルに、コミットの差分を逆に当てて組み立てています。

**調整の前に、コミットの ID で 2 つに分けました。調整に使う 157 本と、取っておく 156 本です。**

| | 調整に使った半分(157) | 取っておいた半分(156)—— 調整前の初回 |
|---|---:|---:|
| 直す前に、コミットが直した所に error が付き、直した後は無い | 34 | **46** |
| 直す前に error が付き、直した後も残る(コミットが一部だけ直した) | 7 | 6 |
| 直す前は warning だけ | 3 | 5 |
| 直す前に何も付かない | 113 | 99 |

取っておいた側を、コミットが直したものの種類で分けると、**リンク 66 本中 36 本、日付 88 本中 12 本、
版 10 本中 1 本**。直された指摘のほとんどは 1 種類で、上に新しい版を足したのに `[Unreleased]` の
リンクが 1〜2 版前から比べたままのもの(313 本全体で直された `LINK` 71 件のうち 66 件)。残りは日付
—— 古いパッチより前の日付の新しいパッチ(`0.5.1` が 2025-04-26 で、その下の `0.5.0` の 2026-04-20
より 1 年前)、`2026-02-30`、2033 年の `0.6.2` —— と、違う版へのリンク(0.2.0 の見出しのリンクが
`v0.1.0` までの比較)です。

取っておいた側と調整に使った側で見つけた直しを入れたあと、313 本を通しで: **直す前に印が付いて
直した後に消えたのが 81 本、一部だけが 12 本、warning だけが 7 本、付かないのが 213 本**(取って
おいた側は 47 本。もう取っておいた側の数ではありません)。1 本では、直したこと自体が error を
足していました。ManoptExamples.jl の Changelog.md は、直した後に `## [0.1.3]` が 2 つあり、
直す前は 1 つでした。

### 見えないもの

付かなかった 220 本(213 本と、warning だけの 7 本)の大半は、変更履歴が自分で示せるものでは
ありません。差分だけで分けると:

| コミットが変えたもの | 本数 |
|---|---:|
| 日付を 14 日以内で動かした —— 実際に出た日へ(`0.2.1 - 2026-08-22` を `2026-08-23` に) | 94 |
| 日付を 15〜62 日動かした(`7 April 2026` を `7 May 2026` に) | 15 |
| 日付をちょうど 1 年動かした | 9 |
| 日付をもっと動かした・埋めた・書き方を変えた | 20 |
| 版はそのままでリンクの URL を変えた: 持ち主やリポジトリの改名、フォーク、リポジトリ名の打ち間違い(`opernai-image-api`)、タグ名の書き方(`16.4.0.rc.10` を `v16.4.0.rc.10` に) | 35 |
| リリースを足し、Unreleased のリンクを一緒に動かした —— 直す前もリンクは正しかった | 27 |
| 版を変えた | 8 |
| 上のうち 2 つ以上 | 12 |

**1 年のずれは、この検査がまさに狙ったもので、9 本のうち 1 本も捕まえていません。**開いて見た 8 本
では、間違った年が隣と比べて浮いていませんでした。全部の項目が一緒にずれていた
(`lukasNebr/stream-web-provider` は 5 項目がそろって 2024 年から 2025 年へ、`internetarchive/heritrix3`
は 2 項目)か、その項目が唯一の、あるいはいちばん古い項目だったからです。デルタチェックには、正しい
隣が要ります。これを捕まえるのは各版の git のタグの日付ですが、この道具は git を読みません(限界を参照)。

### よく知られた 112 本のリポジトリ(2026-09-24)

よく知られた 112 本(React・Vue・ESLint・requests・Flask・rack・Terraform・Grafana・ripgrep・Laravel・
OkHttp・Flutter …。一覧は `replay_fixes.py`)の根にある変更履歴を、調整の前にアルファベット順で
半分に分けました。

| | 取っておいた 56 本 —— 調整前の初回 | 直した後の 112 本 |
|---|---:|---:|
| リリースの項目のある変更履歴 | 52 | 102 |
| 読んだリリースの項目 | 8,655 | 15,617 |
| error | 97 | **29** |
| … 本物 | **13** | **29** |
| warning | 175 | 26 |

**取っておいた側の初回は、ほとんどが外れでした。error 97 件のうち 84 件は本物ではありません。**
54 件は Grafana のセキュリティの出し直し(`13.0.1+security-01` を 2 つ目の `13.0.1` と読んだ)、
12 件は Consul の Enterprise 版(`2.0.2 Enterprise`、`2.0.4+ent`)、4 件は空白を挟んで書いた予告版
(`Version 1.3 beta3`、`2.0.0 rc1`)を正式版と読んだもの、1 件は版を繰り返す小見出し(pydantic)。
日付が 7 件: また Grafana の出し直しと後追いの修正版(5)、Sinatra の 4.0.1 は後追いの修正版で
RubyGems では 2025-05-23、Consul の 1.20.2 は GitHub のリリースと 11 日ずれているだけで 1 年では
ない。`ORDER` が 1 件で fzf の `0.17.0-2`。リンクが 5 件: Composer の RC は分岐点から比べていて、
それで正しい(3)、yargs の 18.1.0 は 18.0.0 から比べていて、ファイルの上ではその間に 17.x の後追いの
修正版がある(1)、見出しの重複のせいで間違って見えたリンク(1)。warning 175 件のうち 135 件は rack で、
`## [3.2.4]` をリンクにせず文字のまま書き、どの版にもリンクを付けない書き方でした。12 件は
highlight.js の作者へのリンク。どれも試験 1 本と直し 1 つになっています。

**直した後、112 本の error 29 件はすべて本物です。**17 件はパッケージの登録簿かリリースのページと
突き合わせました:

- rack 2.2.9(RubyGems: 2024-03-21)、mdBook 0.2.3(crates.io: 2019-01-18)、Rich 10.16.2(PyPI:
  2022-01-02)—— 1 年のずれ
- requests 0.10.2(PyPI: 2012-02-15、変更履歴は 2012-01-15)、Poetry 0.6.1(2018-03-18、変更履歴は
  02-18)、Tailwind CSS 0.6.2(npm: 2018-07-11、変更履歴は 03-11)、Textual 5.1.1(2025-07-31、変更履歴は
  07-21)、Mongoose 1.1.9(2011-03-23、変更履歴は 03-02)—— 1 か月か 1 桁のずれ
- Tailwind CSS 1.7.1 が 2020-08-28 で、上の 1.7.2 は 2020-08-19。npm では 2 つとも 08-19
- Textual の `[7.0.0]`・`[0.80.0]`・`[0.57.0]`、Rich の `[11.0.0]`、TypeORM の 0.3.14 と 0.3.9、HTTPie の
  3.2.1 と 0.2.7 —— 登録簿では先に出ているリリースを飛ばした比較のリンク

残りの 12 件はファイルを読めば分かります: Flutter の 3.19.3 → `tag/3.16.3` と 3.3.7 → `tag/3.3.6`、
Traefik の見出し `v3.0.0-rc5` のリンクが `tree/v3.0.0-rc4`、`v2.9.0-rc1` の見出しが 2 つ(1 つ目のリンクは
`rc2`)、`v2.1.0-rc2` → `tree/v2.0.4`、Commander の `[15.0.0]: …/compare/v15.0.0...v14.0.3`、clap の
`v2.24.0` が 2 つと `v2.4.3` が 3 つ、Alacritty の `0.11.0` が 2 つ、Textual の `0.15.0` が 2 つ。
warning 26 件は、ほかの版にリンクを付けているファイルでリンクの無い見出し 25 件(Tailwind の
alpha 版、Textual の飛ばされた 3 リリース)と、Sinatra の 4.0.1 の `DATE?` です —— 「または版の順に
並べた後追いの修正版」で、実際そうでした。

再生したコミットでは、コミットが触っていない行にも error が出ています。直した後の取っておいた側で
17 件。1 件はリリースのページと突き合わせました(terraform-provider-google の 6.41.0 が 2024-06-24、
GitHub では 2025-06-24)。残りは 1 件ずつは確かめていません。

---

## 限界

- **読むのはファイルで、履歴ではありません。**隣の間に収まる日付は何とも比べないので、実際に出た日の
  1 日前や 1 日後になっている日付 —— 上の直しでいちばん多い種類 —— は通ります。全部の日付がそろって
  1 年ずれた変更履歴も通ります。各項目を git のタグの日付と比べれば両方とも捕まりますが、この道具は
  git を読みません。
- 比較のリンクは、ファイル自身が並べている版とだけ突き合わせます。別のリポジトリを指すリンク
  (改名・フォーク・持ち主の打ち間違い)は見ません。
- 系統をまたいだ `DATE` は、1 年ずらせば説明がつくときだけ報告します。後追いの修正版を版の順に
  並べて正直に日付を付けているプロジェクトでは何も出ません —— その修正版の日付まで間違っていても
  出ません。最後の行が、そういう組を「not reported」として数えます。
- 英語以外の月の名前は読みません。数字の日付だけです。
- AsciiDoc の見出し(`== 1.2.0`)と、Markdown・reStructuredText・プレーンテキスト以外で書いた
  変更履歴(YAML・JSON のリリースファイル)は読みません。

## ファイル

| ファイル | 中身 |
|---|---|
| `changelog_check.py` | 検査 |
| `test_changelog_check.py` | 試験 67 本。後半のほとんどは上の走行で出た偽の指摘で、プロジェクトの名前を付けてある |
| `mutation_check.py` | 検査をわざと壊す 43 通り。**初回に捕まえたのは 39 通り。**3 つは試験の穴(日付だけの行・「Migrating from」で始まる見出し・起点が行き先より新しいリンク)で、1 本ずつ試験を足した。1 つはどう壊しても結果が変わらない条件だったので、コードから取った |
| `replay_fixes.py` | 上の再生: `--search`・`--classify`・313 本のコミット(`--half`)・`--repos` |
