**English: [README.md](README.md)**

# label-link-check —— Bootstrap の不具合報告フォームは、届いた報告に `bug` を付ける。Bootstrap に `bug` というラベルは無い

`twbs/bootstrap` の `.github/ISSUE_TEMPLATE/bug_report.yml` には `labels: [bug]` とあり、README の先頭の
「Report bug」のリンクにも `labels=bug` と書いてあります。このリポジトリのラベルは 69 個で、`bug` はその中にありません
(あるのは `browser-bug` と `confirmed`)。そのときどうなるかは GitHub の issue フォームの説明に書いてあります ——
*"If a label does not already exist in the repository, it will not be automatically added to the issue."*
Bootstrap の issue を `label:bug` で検索すると 0 件、`label:confirmed` なら 1,199 件です。

これが起きても、どこも失敗しません。`github.com/OWNER/REPO/labels/存在しないラベル` へのリンクは **HTTP 200** を返します
(issue の一覧のページで、空の一覧も立派なページだからです)。だからリンク検査はどれも通します。フォームは開き、issue も登録されます。
症状は、振り分け用の検索が黙って少なく返り続けることだけです。

`label_link_check.py` はリンクと issue テンプレートを読み、リポジトリの実際のラベル一覧と突き合わせて、
一覧に無いラベルを名指しし、いちばん近い実在のラベルを添えます。

```bash
python label_link_check.py                       # いまいるチェックアウト(origin のリモートから OWNER/NAME を読む)
python label_link_check.py docs/ --repo OWNER/NAME
python label_link_check.py . --labels labels.json --offline   # `gh label list --json name > labels.json`
python label_link_check.py . --json
```

今日(2026-09-24)の既定のブランチで:

```
$ python label_link_check.py bootstrap
.github/ISSUE_TEMPLATE/bug_report.yml:4: error LABEL twbs/bootstrap: template label "bug" does not exist in twbs/bootstrap, so issues filed with this template never get it
README.md:15: error LABEL twbs/bootstrap: label "bug" does not exist in twbs/bootstrap

$ python label_link_check.py flutter
docs/about/Project-teams.md:29: error LABEL flutter/flutter: label "team: infra" does not exist in flutter/flutter (did you mean "team-infra"?)
docs/engine/Using-Sanitizers-with-the-Flutter-Engine.md:54: error LABEL flutter/flutter: label "sanitizer" does not exist in flutter/flutter (did you mean "from: sanitizer"?)

$ python label_link_check.py p5.js
contributor_docs/contributor_guidelines.md:78: error TEMPLATE processing/p5.js: template found-a-bug.yml is not in processing/p5.js/.github/ISSUE_TEMPLATE (did you mean 2-found-a-bug.yml?)
contributor_docs/ja/contributor_guidelines.md:78: error LABEL processing/p5.js: label "Bug\" does not exist in processing/p5.js (did you mean "Bug"?)
```

p5.js はテンプレートの名前の頭に番号を付けましたが、貢献ガイドは古い名前にリンクしたままで、**6 つの言語版を合わせて 30 か所**あります。
日本語版と中国語版はさらに `labels=Bug%5C` —— 翻訳のどこかの段で URL の中にバックスラッシュが入り、GitHub に渡るラベル名は `Bug\` になっています。

Python の標準ライブラリだけで動きます。読むのはファイルと GitHub のラベル一覧だけで、何も実行せず、書かず、投稿しません。
誤りがあれば終了コード 1、無ければ 0、**調べるリポジトリ自身のラベル一覧が読めなかったときは 2** です(何も読めなかった検査が合格を出してはいけないため)。

---

## 何を報告するか

| コード | 重さ | 意味 |
|---|---|---|
| `LABEL` | error | そのラベルがリポジトリに無い。大文字小文字は区別しない(GitHub の検索も区別しない)。`…/labels/名前`、`issues?q=label:…`、`issues?labels=a,b`、`issues/new?labels=…`、`github.com/issues?q=repo:… label:…`、それに issue テンプレートの `labels:` を読む |
| `TEMPLATE` | error | `issues/new?template=x.yml` が `.github/ISSUE_TEMPLATE/` に無いファイルを指している。そのフォルダ自体が無いリポジトリは、GitHub が既定を取ってくる持ち主の `.github` リポジトリも見る。`template=BLANK_ISSUE` は GitHub 自身の名前でファイルではない |
| `UNQUOTED` | error | `label:good first issue` —— GitHub はラベル `good` と 2 語の本文として読む。1 つのラベルになるのは `label:"good first issue"` だけ。引用符で囲んだ形が実在のラベルのときに出す |
| `QUOTED_PATH` | error | `…/labels/%22good%20first%20issue%22`。ラベルのページは引用符を**名前の中に**入れる。そのページ自身が組む検索式は `label:"\"good first issue\""` |
| `IS_VALUE` | error | `is:opened`、`state:all` —— その修飾子が取らない値。検索は何にも当たらない |
| `NO_REPO` | error | リンク先のリポジトリが見つからない(削除か非公開)。改名したリポジトリは転送されるので問題ない |
| `CASE` | warning | ラベルはあるが、大文字小文字が違う |
| `OR_LABEL` | warning | `label:a,b` の片方だけが無い。もう片方の issue は出る |
| `NEG_LABEL` | warning | 無いラベルの `-label:x` は何も除かない |
| `QUALIFIER` | warning | `lable:bug` —— 修飾子ではないので、本文の文字列として検索される |
| `PLUS_PATH` | warning | `…/labels/help+wanted`。パスの中の `+` は空白ではなくプラス記号(`vuejs/core` の `good+first+issue` は REST API で 404) |
| `UNCHECKED` | warning | ラベルかテンプレートの一覧が読めず、そのリンクは判定していない |

**別の**リポジトリへのリンクは、そのリポジトリのラベルと突き合わせます(ラベル 100 個ごとに API 1 回)。
100 ページを超えても終わらない一覧は、読みかけのまま使わず「読めなかった」扱いにします ——
私たち自身の計測が最初 `elastic/kibana` の 1,665 個のラベルを 1,000 個で切り、実在する 4 つのラベルを 4 件の誤りにしたからです。
ラベルは `--labels` か、REST API から読みます(`GITHUB_TOKEN` / `GH_TOKEN` があれば使う。無ければ 1 時間 60 回まで)。

---

## 正しいとどうして言えるか

以下はすべて 2026-09-24 の計測です。このリポジトリの道具はどれも同じ 2 つで確かめています ——
**人が手で直したコミットを、直す前と後で再生する**ことと、**調整の前に取っておいたリポジトリで、最初の版の精度を出す**ことです。

**よく知られたリポジトリ。** star が 30,000 を超える上位 300 と、5,000〜30,000 で good first issue を持つ 200 ——
アーカイブ済みと重複を除いて 486。その README・貢献ガイド・docs・`.github/` の **16,793 ファイル、リンクとテンプレートのラベル 2,614 個**。
調整の前に名前のハッシュで半分に分けました。

| | 取っておいた 245・最初の版 | 486 全部・最終版 |
|---|---:|---:|
| `LABEL` の誤り | 97 | 150 |
| …裏が取れたもの | **93** | **150** |
| `TEMPLATE` の誤り | 43 | 54 |
| …裏が取れたもの | **43** | **54** |
| 誤りが 1 件以上あるリポジトリ | 45 | 86 |

「裏が取れた」は、ラベルなら「一覧に無く、**かつ** GitHub の検索がそのラベルで返す issue と PR(それぞれ先頭 30 件)のどれも、今そのラベルを持っていない」こと、
テンプレートなら「リポジトリの `.github/ISSUE_TEMPLATE/` にも、持ち主の `.github` リポジトリにも無い」ことです。
取っておいた側で裏が取れなかった **4 件**は、私たちの計測用の道具が 1,000 個で切った `elastic/kibana` のラベルです
(検査器そのものは当時 3,000 個まで読み、今は読み切れない一覧を使いません)。
偽の `TEMPLATE` は調整用の側で 1 件だけ見つかり(`scikit-learn` の `template=BLANK_ISSUE`)、その名前を飛ばすようにしたのはこのためです。
取っておいた側の警告は `CASE` 14・`NEG_LABEL` 5(いずれも事実どおり)と、外れた `QUALIFIER` 1 件 —— `title:` は検索の修飾子として効くので、今は知っています。

issue テンプレートを持つ 366 リポジトリのうち、**62 が実在しないラベルを 1 つ以上名指ししていて、合わせて 100 個**でした。
`open-webui`(`triage`)、`langchain`(`task`)、`llama.cpp`(`compilation`・`model evaluation`・`refactoring` のつもりの `refactor`)、
`github/spec-kit`(`bug`・`agent-request`)、Next.js の不具合フォーム(`type: example`・`template: bug`、それにもう無い `2.example_bug_report.yml` へのリンク)などです。

**検索の索引は、消したラベルを覚えている。** 150 個のうち 7 個は、GitHub の検索がまだ issue を返します ——
`facebook/docusaurus` の `label:"help wanted"` は 186 件を返し、**先頭 30 件のどれも今はそのラベルを持っていません**。
つまり CONTRIBUTING.md のそのリンクは空ではなく、もう無いラベルの名前で古い issue を並べています。
上の「裏が取れた」を「検索が何か返したか」ではなく「返った issue がそのラベルを持っているか」で見ているのもこのためで、
私たちの最初の裏取りは件数を数えていて、本物の 6 件を偽と判定しました。

**人が手で直したコミット。** 46 通りの言い回し("fix good first issue link"、"fix issue template label"、"nonexistent label" …)でコミットを検索し、
親が 1 つでメッセージがラベルかテンプレートに触れているもの 4,769 本、GitHub の issue へのリンクか `labels:` の行を消したもの 606 本、
**ラベルのリンクかテンプレートの `labels:` を変えたもの 164 本**。調整の前にコミットのハッシュで半分に分けました。
1 本ごとに、変わったファイルの前と後、今日のラベル、それぞれの時点のテンプレートのフォルダで検査しています:

| | 取っておいた 80・最初の版 | 164 全部・最終版 |
|---|---:|---:|
| 前にあった誤りが後に消えた(**捕捉**) | **36** | 72 |
| 前と後で同じ誤り | 9 | 17 |
| 後にだけ誤り | 1 | 4 |
| 前にあった警告が後に消えた | 0 | 1 |
| どちらにも誤り無し | 34 | 70 |

取っておいた側で誤りが出なかった 34 本は全部読みました。**捕まえるべきだったのは 1 本**:
`labels/good%20first%20issue!` —— 検査器はリンクの後ろの `!` を句読点として削りますが、ここでは URL の一部でした。
**もう 1 本は、調整用の側で入れた直しで捕まるようになりました**(URL の中の引用符、`label%3A"good+first-issue"`)。
残りの 32 本は、ラベルやテンプレートが無いという話ではありませんでした —— 別の実在するラベルへの付け替え、GitHub が転送する改名後のリポジトリへの付け替え、
組織全体・ユーザー全体の検索への広げ(これは見ていない)、フォームの本文のチェックボックスの `label:`、書式や言い回し。

「前と後で同じ誤り」はコミットが別のものを直していた場合で、コミットの後にも間違ったままのラベル 49 個はすべて検索で裏が取れています。
**「後にだけ誤り」の中に、知っておく価値のある 1 本があります**: vercel/next.js の #80478
*"chore: fix link to good first issue … Link to good-first-issue lacked some encoding"*(2025-06-13)は、
`labels/good%20first%20issue` を `labels/%22good%20first%20issue%22` に変えました。その URL でラベルのページが組む検索式は
`label:"\"good first issue\""` です。リンクはその後、元に戻されています。

`replay_fixes.py` は `replay_commits.tsv` の 164 本を再生します。ラベル一覧のほかに GitHub から読むのは、このフォルダではこのファイルだけです。

---

## しないこと

- **ラベルの昔の名前は知らない。** `sanitizer` が無いと言って `from: sanitizer` を勧めるのは、同じ語で終わるラベルがそれ 1 つだからで、改名があったことまでは分からない
- **組織全体・ユーザー全体の検索**(`org:`・`user:`)は見ない。ラベルはリポジトリごとのものだから
- **相対リンク**(`../../labels/bug`)は読まない
- **文書に書かれていない GitHub の規則は知らない。** テンプレートの `labels:` の文字列は、仕様のページのとおりカンマで区切る。
  だから `rust-lang/rust` の `labels: C-tracking-issue T-compiler A-lints` は 1 つのラベル名として報告する。
  YAML のリストの 1 項目の**中の**カンマで GitHub が区切るかは書かれていないので、区切って読む(GitHub が付けたかもしれないラベルを誤りとは言わない)
- **URL の最後の `!` や `.` は句読点として扱う** —— 上の、取っておいた側での 1 本の取りこぼし
- テンプレートとリンクの **issue の種類・プロジェクト・マイルストーン**は見ない

## CI で

```yaml
- uses: actions/checkout@v4
- run: python tools/label_link_check.py .
  env:
    GITHUB_TOKEN: ${{ github.token }}
```

`label_link_check.py` は 1 ファイルなので、`run:` の行が指す場所に写してください。この例は、私たち自身はまだ GitHub Actions で動かしていません。

## 試験

`python test_label_link_check.py` —— 83 件。`python mutation_check.py` は検査器を 41 通りに 1 か所ずつ壊し、試験が気づかなければ失敗します。
**41 通りすべて捕まり、最初の回は最初の 29 通りのうち 27 通りでした**(HTML のリンクに `&amp;` が残る壊し方と、検索式の語にかっこが付いたまま残る壊し方の 2 つが生き残りました。
どちらも、試験がその違いの出ない書き方になっていたためです)。

このリポジトリ自身の 5 つの issue テンプレートが、実在しないラベルを 6 つ名指ししていました(`key-expiry-result`、`jira-apps` …)。
検査器が最初に見つけたのはこれです。2026-09-24 にラベルを作り、今は 0 件です。
