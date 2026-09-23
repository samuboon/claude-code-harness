**English: [README.md](README.md)**

# forge-scope-check —— 自分たちの Forge アプリ 5 本のうち 2 本は、ボードもグループの構成員も 1 件も読めない作りだった。どのファイルを見ても正しく見えていた

Forge アプリは `manifest.yml` にスコープを書き、コードは `api.asApp().requestJira(route`...`)` で Jira を呼びます。この 2 つを突き合わせるものは、実際のサイトに入れて 403 が返るまでどこにもありません。私たちは自分のアプリでそれに気づきました。サイトに入れる前に、呼び出しを 1 本ずつ Atlassian の API 定義に当てて数え直したからです。

- **スプリントの日付で絞る JQL 関数は、`read:jira-work` しか宣言していませんでした。**ボードとスプリントを読む 4 つの呼び出しは全部 Jira Software 側(`/rest/agile/1.0/...`)にあり、Jira Software には classic のスコープがそもそもありません。Forge の文書は 1 行で書いています ——「Jira Software doesn't support classic scopes. Use granular scopes instead.」([出典](https://developer.atlassian.com/platform/forge/manifest-reference/scopes-product-jsw/))。どの検索にも何も返さないところでした
- **プロジェクトロールの構成員で絞る JQL 関数は、`GET /rest/api/3/group/member` を必要なスコープなしで呼んでいました。**このアプリの存在理由であるグループの構成員が、1 人も返らないところでした
- **2 本とも JQL 関数から `api.asUser()` を呼んでいました。**`requestJira` の説明は「This context method is only available in modules that support the UI kit.」([出典](https://developer.atlassian.com/platform/forge/apis-reference/fetch-api-product.requestjira/)。2026-09-23 に確認)。JQL 関数はそれに当たりません

`forge_scope_check.py` は、この手作業の照合を機械で行います。

```bash
python forge_scope_check.py path/to/forge-app             # 報告
python forge_scope_check.py path/to/forge-app --tsv       # 呼び出し・指摘ごとに 1 行
python forge_scope_check.py app --allow-deprecated        # 非推奨の呼び出しを失敗でなく警告にする
```

Python 標準ライブラリのみ。Node も Forge CLI も要らず、検査のときに通信もしません。

---

## 何を見るか

`manifest.yml` と `src/` の下の `.js/.jsx/.ts/.tsx/.mjs/.cjs` をすべて読み、`requestJira(route`...`)` を 1 本ずつ拾って、道の直後の options(同じファイルで定義した定数、または `const get = (path) => api.asApp().requestJira(path, OPTS)` のような小さな包み関数を通したものも含む)から HTTP のメソッドを読みます。そのうえで `jira_scopes.json` —— Atlassian が公開している Jira platform と Jira Software の OpenAPI 定義から 2026-09-23 に作った **724 件**の対応表 —— に当てます。

| 指摘 | 意味 |
|---|---|
| `MISSING` | 宣言したスコープが、その呼び出しに要る classic の組の全部も、granular の組の全部も満たしていない。granular の組の半分では足りない。Jira Software の呼び出しでは「`read:jira-work` では開かない」と添える |
| `ASUSER` | UI を持たない module(JQL 関数・trigger・scheduledTrigger・webtrigger など)からしか辿り着かない関数の中で、account id なしの `api.asUser()` を呼んでいる。同じファイルが UI の resolver にも使われているときは、どの export の中の呼び出しか見分けられないので警告に下げる |
| `DEPRECATED` | 定義が非推奨と印した呼び出し。既定で失敗にする —— 私たちは非推奨の呼び出し 2 本を警告のまま 1 日残し、誰もその警告を読まなかった。`--allow-deprecated` で警告に戻せる |
| 警告 `UNUSED` | どの呼び出しも要求しない宣言。全部の呼び出しを検査できたときだけ出し、`storage:app` など REST の呼び出しでは正当化できないスコープには出さない。製品イベントが要るスコープは見えない |
| 警告 `REDUNDANT` | その classic を要る呼び出しが全部、宣言済みの granular で既に開いている |
| `unchecked` | 解決できなかった呼び出し(道が変数・メソッドが変数・Confluence や Bitbucket・表に無い口) |

**終了コード:** 0 = 全部の呼び出しを検査して指摘なし / 1 = 指摘あり / 2 = アプリを読めない(manifest が無い・この読み手が扱わない YAML —— アンカーや flow の対応 —— ・コードが無い)/ **3 = 指摘は無いが、検査できなかった呼び出しがある。これは合格ではない。**0 とわざと分けています。呼び出しの半分を飛ばして「問題 0 件」と言う検査器は、無いより悪いからです。

---

## 答えが分かっているアプリで測った

私たちの Forge アプリ 5 本(JQL 関数とカスタムフィールド)を、2026-09-18 の 2 つの時点で:

| 版 | 検査した呼び出し | 未検査 | 指摘 |
|---|---|---|---|
| 手で直す前 | 26 | 0 | **5 本中 3 本**: `MISSING` 6(Jira Software の 4 本・`group/member` 2 本)・`ASUSER` 10 行・`DEPRECATED` 2(`/rest/api/3/search`・`/rest/agile/1.0/board/{}/issue`)。ほかに `UNUSED` の警告 1 |
| いま | 23 | 0 | 5 本とも **0** |

1 行目の指摘は、使っていなかった `read:jira-user` も含めて全部、その日に手で見つけて 2 つのコミットで直したものです。この道具は対応表だけからそれを全部拾い、それ以外は何も拾いませんでした。5 本が呼ぶ 18 種類の口については、09-23 に作った表と、09-18 に手で写した表が 18 件とも一致しました。

試験 41 本。`mutation_check.py` は検査器を 21 通りに壊し(granular の組の半分を足りたと数える・全部の呼び出しを GET と読む・未検査を合格と数える・UI の resolver を見分けない など)、そのたびに試験が落ちることを確かめます。**初回に捕まえたのは 21 通り中 18 通り**でした。生き残った 3 つは本物の穴でした —— UI だけから呼ばれる関数が警告として出ても気づかなかった / 「字面の一致が多い口を選ぶ」規則は、試験の道が全部ぴったり一致していたので一度も通っていなかった / granular の組の半分で `REDUNDANT` が鳴る場合を試していなかった。3 つに試験を 1 本ずつ足して 21 通り中 21 通りです。

**当てたアプリは全部自分たちの物です** —— 同じ手・同じ書き方の 5 本・23 か所。他人の Forge アプリに 1 度当てて、当たったか外れたかが分かるほうが、この表全体より価値があります。`forge lint` とは比べていません(Node と Forge CLI が要り、ここでは走らせられませんでした)。

---

## しないこと

- Jira だけ。`requestConfluence` / `requestBitbucket` は `unchecked` で返す
- 包み関数は名前で 1 段だけ(ファイルをまたいで)追う。options を入れた定数は同じファイルで定義されたものだけ読む。それより動的なものは `unchecked`
- `asUser()` は関数の本体ではなくファイル単位で見る。ファイル間の import は追わない
- 製品イベント(`avi:jira:...` の trigger)が要るスコープは知らない
- 表は作った日の分だけ新しい。`python build_table.py --diff` で定義を取り直して変わった口を出し、`python build_table.py` で表を書き直す(1 行 1 口なので差分が読める)。platform の 3 つの口(`/rest/api/3/uiModifications`)は granular の印の下に `read:jira-work` を載せており、表は印に従ったうえで `meta.anomalies` に記録している

```bash
python -m unittest test_forge_scope_check -v
python mutation_check.py
```

MIT(このリポジトリの他と同じ)。
