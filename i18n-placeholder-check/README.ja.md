**English: [README.md](README.md)**

# i18n-placeholder-check —— Jenkins は 2008 年から 12 回のコミットでこれを 34 件、手で直してきた。それでも今日の master は、エージェントの名前が入るはずの所に `{0}` と出す

`java.text.MessageFormat` は、アポストロフィ `'` を「ここから引用」の印として読みます。英語の試験が
通らない訳文の中では、これが静かな不具合になります。

```properties
# hudson/model/Messages.properties                (基底。活字の引用符 ‘ ’ を使っている)
ComputerSet.SlaveAlreadyExists=Agent called ‘{0}’ already exists
# hudson/model/Messages_pt_BR.properties          (ASCII の ' 。2026-09-24 の Jenkins master)
ComputerSet.SlaveAlreadyExists=O agente chamado '{0}' já existe
```

ポルトガル語の文は `O agente chamado {0} já existe` と出ます。波かっこがそのまま出て、名前は入りません。
イタリア語の `Il valore dev'essere maggiore o uguale a {0}` は `Il valore devessere maggiore o uguale a {0}` になります。
ファイルは読み込め、鍵もそろっていて、英語の画面は正常で、どこも失敗しません。

`i18n_placeholder_check.py` は `.properties` の束を `Properties.load` と
`MessageFormat.applyPattern` と同じ規則で読み、訳ごとに基底のファイルと突き合わせます。

```bash
python i18n_placeholder_check.py src/main/resources
python i18n_placeholder_check.py src/main/resources --always-messageformat --key-as-base   # Jenkins・Stapler
python i18n_placeholder_check.py src/main/resources --tsv                                  # 1 件 1 行
```

```
.../Messages_pt_BR.properties:127: error QUOTED ComputerSet.SlaveAlreadyExists: an apostrophe quoted {0}; prints: O agente chamado {0} já existe
.../Messages_it.properties:178: error QUOTED Hudson.MustBeAtLeast: an apostrophe quoted {0}; prints: Il valore devessere maggiore o uguale a {0}
.../changes_tr.properties:25: warning APOS from.label: a lone apostrophe is eaten by MessageFormat; prints: #<0>dan
```

`prints:` の中の `<0>` は引数 0 が入る場所で、そこに `{0}` と見えていれば、それはそのまま出てしまう `{0}` です。
標準ライブラリだけで動きます。ファイルを読むだけで、書き込みも通信もしません(下の `replay_fixes.py` だけは読みに行きます)。

---

## 出すもの

| 印 | 重さ | 意味 |
|---|---|---|
| `BROKEN` | error | `MessageFormat` がその値で `IllegalArgumentException` を投げる。閉じていない波かっこ・`{}`・`{name}`・`{{0}}`・知らない型・壊れた choice(選ばれたときに投げる choice の枝も含む) |
| `QUOTED` | error | アポストロフィが始めた引用が、基底の使う置き場所を飲み込んだ。`{0}` の字のまま出る |
| `BADFILE` | error | ファイルがそもそも読めない(壊れた `\uXXXX`。`ResourceBundle` はファイルごと断る) |
| `APOS` | warning | パターンとして読まれる値に、対になっていない `'` がある。出力から消える(`n'existe` → `nexiste`)。波かっこを含む引用(`'{'`)は波かっこを出すための正式な書き方なので出さない |
| `MISSING` | warning | 基底が使う置き場所を訳が使っていない |
| `EXTRA` | warning | 基底に無い置き場所を訳が使っている。呼ぶ側が基底より多く引数を渡していない限り、`{2}` の字のまま出る |
| `BOM` | warning | ファイルの先頭に BOM がある。`Properties.load` は取り除かないので、最初の鍵が U+FEFF 付きになり、一致しない |
| `TYPE` | note | 基底が素のまま出す置き場所に、訳が型を付けた(基底 `{0}` に対して複数形のための `{0,choice,...}` など)。数なら問題なく、文字列なら `Cannot format given Object as a Number` を投げる。型を**外した**訳は出さない —— `{0}` と `{0,number}` は数を同じに出すため |
| `ORPHAN` | note | 基底に無い鍵。値そのものの検査はする |
| `DUP` | note | 1 つのファイルに同じ鍵が 2 回(後のほうが勝つ) |

**どの値をパターンとして読むか。** 既定では、基底の値に置き場所が 1 つ以上ある鍵だけです(引数が
あるときだけ `MessageFormat.format` を呼ぶコードが多いため)。隣に訳が 1 つも無い `.properties` は
設定ファイルとみなし、読みません。`--always-messageformat` は全部の値をパターンとして読みます。
**これが Jenkins の流儀です。**Jenkins 自身の履歴がそう言っています —— `db7a19810d`「MessageFormat
treats ' as a special character」、`655601ebb3`「Unescaped apostrophes were dropped from message
formats」は、どちらも置き場所の無い文を直したコミットです。

**鍵が原文そのもののとき。** Jelly の画面では `${%Other Jenkins}` と書くと英語の文そのものが鍵になり、
訳のファイルに基底のファイルが無いことがよくあります。`--key-as-base` はそういう鍵を、鍵そのものと
突き合わせます。対象は空白か波かっこを含む鍵だけで、`PluginWrapper.disabled` のような識別子を
原文と取り違えません。`--base-locale en` は `Messages.properties` が無いときに `Messages_en.properties`
を基底にします。

**Java 21 か 25 か。** `--java 21`(既定。ここでは Java 8〜21 は同じ動き)は型を `number`・`date`・
`time`・`choice` の 4 つだけ知っていて、choice の枝の中の引用されていない `#` を区切りとして読み、
投げます。`--java 25` はそれに加えて `dtf_date`・`dtf_time`・`dtf_datetime`・`list` と `iso_*` の名前を
受け、枝の中の `#` を文字として残します。Jenkins の master では、どちらでも結果は同じでした。

**終了コード:** 0 = 誤りなし(警告は `--strict` のときだけ失敗)。1 = 誤りあり。
2 = `.properties` が 1 本も無い。**3 = 失敗は無いが、基底の無い訳があって突き合わせていない**
(`--key-as-base` か `--base-locale` を使う)。3 は合格ではありません。

---

## 実測

### Jenkins 自身の修正を再生した(`replay_fixes.py`)

Jenkins のリポジトリの履歴からアポストロフィと引用符についてのコミットを探し、`.properties` を
変えている 15 本を取りました。1 本ごとに、値が変わった鍵をすべて、コミットの**前**と**後**で検査しました
(`--always-messageformat --key-as-base`)。

| コミット | 変わった鍵 | 前に印が付いた | 後にも残った |
|---|---|---|---|
| `MessageFormat` に食われたアポストロフィを直した 12 本(2008〜2019 年) | 36 | **36** | 2 |
| 書き方を変えただけの 3 本(`''` → `’`、`''` → `„“`、短縮形を書き下した) | 96 | **0** | 0 |

後にも残った 2 件は、そのコミット自身が残したものです。`8a8fbbaad6`(「Spelling and proper escaping
for apostrophes」、2009 年)は「it'll wrec havoc」の綴りを直してアポストロフィを残し、それは 2019 年の
`527c5935fd`(JENKINS-55834)で直りました。`655601ebb3` は同じ文の中に `href='...'` を残し、今日の
master では二重引用符になっています。
**`--always-messageformat` を付けないと、36 件のうち 4 件にしか印が付きません。**直された文の多くには
置き場所が無く、既定の読み方がまさに見送る場合だからです。

```bash
python replay_fixes.py            # 変わった鍵ごとに前後の値を出す。-q で 1 コミット 1 行
```

### 今日の Jenkins master(コミット `bdefb3e`、2026-09-24 に読んだ)

`.properties` 7,489 本、束 348。

| 読み方 | 突き合わせた鍵 | `BROKEN` | `QUOTED` | `APOS` | `MISSING` | `EXTRA` | `TYPE`(note) |
|---|---|---|---|---|---|---|---|
| 既定 | 19,806(基底の無い 2,993 本は突き合わせず。誤りが無ければ終了コード 3) | 1 | 11 | 8 | 95 | 15 | 35 |
| `--always-messageformat --key-as-base` | 27,600 | 9 | 11 | 80 | 95 | 17 | 35 |

- **`QUOTED` は 10 の文に 11 件**: ブラジル・ポルトガル語の 6 文に 7 件(基底の `‘{0}’` を `'{0}'` と
  書いた)、イタリア語 2 件(`dev'essere`)、トルコ語 2 件(`#{0}'dan #{1}'a`、`'{0}' adlı`)。どれも名前や
  ビルド番号の代わりに `{0}` や `{1}` の字が出ます。
- **`BROKEN`**: どちらの読み方でも 1 件 —— エストニア語の `kataloog {{0}}`。木全体に
  `--always-messageformat` を当てると、ほかに 6 件が Maven のフィルタ用の雛形(`src/filter` の下の
  `${project.version}`)で、これは文ではありません。残り 2 件は訳の鍵の `:` が逃がされていないもの
  (`Log:\ ${my.displayName}`)で、ファイルが定義するのは鍵 `Log` になり、その訳は一度も使われません。
- **`APOS`**: 80 件。トルコ語 19・フランス語 13・イタリア語 10 ほか。英語の基底にも 1 件
  (`_safeRestart.properties` の「if you don't supply one」)。
- **`TYPE`**: 35 件のうち 33 件は `Util.second`・`Util.year` などに複数形を足した訳で、引数は数です。
  残る 2 件(ドイツ語・イタリア語)も、基底が素のまま出すものを数として書式化しています。`TYPE` を
  note にしたのはこのためです。

**確かめていないこと。** どれも動いている Jenkins の画面では見ていません。測った端末には Java が
ありません。構文解析は OpenJDK の `jdk21u` と `jdk25u` の `MessageFormat`・`ChoiceFormat`・`Properties` の
ソース(2026-09-24)と読み比べて合わせたもので、実行して比べたものではありません。ある Jelly の画面が
引数の無い文も書式化するかどうかは Jenkins 側の実装で、そう読んでいる根拠は上の修正の履歴です。

---

## できないこと

- **`java.text.MessageFormat` だけ。**ICU の MessageFormat(`{count, plural, one {...} other {...}}`・
  `select`)、Android の `strings.xml`、gettext、JSON のカタログは読みません。
- 数と日付の**書式の中身**(`{0,number,#.##}`)は検査しません。Java では投げる壊れた `DecimalFormat` の
  パターンも、ここでは通ります。
- JDK の癖を 2 つわざと残しています。内側の波かっこが開いたまま終わった引数(`{0,choice,0#{1`)は
  `applyPattern` と同じく黙って捨て、`{+1}` は引数 1 とします。
- `help.properties` の隣の `help_ant.properties` は言語 `ant` の訳として読みます。その言語を求められれば
  Java も同じように読みます。
- 試験 55 本。`mutation_check.py` は道具を 26 通りに壊し、26 通りとも捕まります。**最初の実行は 22 通り
  中 21 通り**でした —— ファイル名の語幹を短い順に試す誤り(`Messages_pt_BR` を `Messages_pt` の訳と
  読む)は、`help_ant_de.properties` の試験を足すまで見つかりませんでした。OpenJDK のソースを読んだ後に
  足した 4 通り(Java 25 の型・choice の枝の中の `#`・引数番号の上限 10,000・前に空白のある無限大の区切り)は、
  最初から捕まりました。
