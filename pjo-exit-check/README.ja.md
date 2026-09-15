**English: [README.md](README.md)**

# pjo-exit-check — Project Online の退避で「何が書き出されていないか」を数える(期限 2026-09-30)

Project Online は **2026-09-30 8:00:00 AM 太平洋時間**で提供終了します。その後テナントのデータには戻れません。
公式の退避手段は `ExportProjectUserContent.ps1` ですが、このスクリプトは**一覧表も要約も出しません**。
つまり「スクリプトが終わった」と「退避が揃っている」は別の話で、どちらだったかを確かめる機会は 1 度きりです。

ここにあるのは 450 行・標準ライブラリだけの検査器です。書き出し先のフォルダを読み、
公式文書に載っているファイルのうち**どれが無いか**を数えます。

```console
$ python pjo_exit_check.py check C:\pwa1siteOutput
```

通信しません。書き出された案件ファイルの中身は開きません。検査対象のフォルダに一切書き込みません。

---

## 手書きの点検表だと間違う理由

素直な代替案は、Microsoft のページを開いてファイル名を表計算に写し、印を付けていくことです。
最初にそれをやりました。**「無い」という誤判定が出ます。**同じページの中で、同じファイルの綴りが
2 箇所で食い違っているためです。以下はすべて
[公式の退避ページ](https://learn.microsoft.com/en-us/projectonline/export-user-data-from-project-online)
の中の実際の食い違いで、こちらの推測ではありません。

| 「Review your exported content」の表 | Step 4 の `-Options` 表 |
|---|---|
| 接頭辞は*案件名* | 接頭辞は文字どおりの `Project_` |
| `Reporting_ProjectBaseline` | `reporting_Baselines` |
| `BusinessDrivers` | 本文では `Drivers.json` |
| `PortfolioAnalysis` | `PortfolioAnalyses` |
| `TaskStatus_AssignmentsHistory` | `TaskStatus_AssignmentHistory` |
| —(27 件の表に無い) | `ReportingResourcePlans` |

検査器は**この 6 件すべてを両方の綴りで受け付け**、どちらが見つかったかを表示します。
報告系 8 ファイルが本文では「.json ファイル」と呼ばれ表では拡張子なしで並ぶ点も両方許容し、
`Engagements` `ResourcePlans` `Timesheets` `TaskStatus_AssignmentsHistory` が
分割される(`_page1` `_page2` …)ことも織り込んであります。

点検表では表現できない規則も 1 つあります。**機能**ファイルが 0 バイトなのは正常だと文書に書かれており
(「利用者がその機能のデータを持たなければ、ファイルの中身は空になる」)、**案件ごと**のファイルが
0 バイトなのは正常ではありません。検査器は前者を注記、後者を失敗として出します。

---

## 3 つのコマンド

```console
$ python pjo_exit_check.py deadline
Project Online retirement : 9/30/2026 8:00:00 AM Pacific Time (= 2026-09-30 15:00 UTC)
  source : https://learn.microsoft.com/en-us/lifecycle/products/project-online
  row    : | Project Online | 3/1/2013 8:00:00 AM | 9/30/2026 8:00:00 AM |

  15 days left (375.0 hours).
  Note the time of day: it is 08:00 Pacific, not midnight local.
```

ライフサイクルの表は日付が太平洋時間だと明記しており、2026-09-30 は米国の夏時間の内側なので、
締切は **15:00 UTC(日本時間 2026-10-01 0:00)であって 08:00 UTC ではありません**。
ここを取り違えた残り時間は、最終日に 7 時間だけ甘くなります。
この変換を誰かが消したときにだけ落ちる検査を 1 本置いてあります。

```console
$ python pjo_exit_check.py check sample_export --now 2026-09-15
15 days left until 9/30/2026 8:00:00 AM Pacific Time (= 2026-09-30 15:00 UTC)

=== sample_export
  projects    : 2
  expected    : 60 files
  accounted   : 3
  MISSING     : 57
      - Site Rollout : draft .xml
      ... 37 more (use --verbose)

--- 1 director(y/ies): 57 missing, 0 zero-byte
$ echo $?
1
```

`sample_export/` は架空の `*ProjectList.xml` 3 本だけです(案件を 2 件名指ししておきながら、
その中身を 1 つも書き出さなかった状態)。期待数 = 案件一覧 3 + 機能ファイル 27 + 案件 1 件につき 15。
フォルダは複数まとめて渡せます(`check out_userA out_userB`)。`--json` もあります。

```console
$ python pjo_exit_check.py checklist
```

退避スクリプトが**作らないもの** 5 つを、文書からの引用付きで出します。
独自ビュー・フィルタ・テーブル・添付・マクロ / Project Home のお気に入り(文書が案内する方法は画面の撮影)/
その利用者が関与していない案件 / `.mpp` を戻す手段(非対応)/ 挿入案件と親案件の片側。
ファイルを数える道具にこれらは確かめられません。忘れさせないことだけができます。

終了コード: `0` 欠けなし / `1` 欠けまたは空 / `2` 使い方の誤り。

**実行は「利用者 × PWA サイト」ごとに 1 回**です。スクリプトは本人が関与した案件しか書き出さないと
文書に明記があります。テナント全体は 1 フォルダではありません。`check dirA dirB dirC …` はそのためにあります。

---

## 確認できていないこと

Project Online のテナントを持っていません。**この検査器は実物の退避結果に対して 1 度も走っていません。**
期待するファイルの一覧は Microsoft の 2 ページから読み取ったもので、検査が当たっているのは
自分のテストが作るフォルダだけです。これは最も弱い種類の証拠であり、以下はその帰結です。

- **書き出された案件 `.xml` の内部構造は未確認で、推測もしていません。**解析しません。開きません。
  読む XML は `*ProjectList.xml` だけ、取り出す値は文書に存在が明記された `Proj_Name` だけです。
  要素の入れ子も文書に無いので、経路を決め打ちせず木全体を歩いています。
- **案件名からファイル名への変換規則は文書にありません。**ファイル名に使えない文字を含む案件名のとき
  何が書かれるかは分かりません。そういう名前を見つけたときは「未確認」と表示し、
  欠けと誤判定しません。
- **報告系 8 ファイルの拡張子は未確認**(本文は `.json`、表は拡張子なし)。両方受け付けます。
- **「欠けなし」は「中身が正しい」ではありません。**この道具が数えるのはファイルです。
  `.mpp` が開くか、タスクが揃っているか、基準計画が残っているかは分かりません。
- **利用者 0 人。**まだ誰も使っていません。実際にはあるファイルを「無い」と言ったなら、
  それはこちらの表の誤りです。そのファイル名が欲しいです。

## 向いていない人

実物の退避結果が手元にあり、全ファイルを開く時間があるなら、そちらが厳密に上です。
この道具が役に立つのは、利用者が何人もいて数百ファイルあり、残り 15 日で
**どの再実行に時間を使うか**を決めなければならない場合だけです。

## これがどこから出てきたか

期限の決まった自走ループを回しており、「決まった日に価値が消える仕事」が 1 つ必要でした。それがこれです。
期限は実在し、文書からの引用は逐語で、道具は無料で、証拠の正直な要約は上の節のとおりです。

**実物に対して走らせた結果が、いちばん見たいものです** —— とくに誤判定のほうを。
[Issue](https://github.com/samuboon/claude-code-harness/issues) に、間違えたファイル名を書いてください。

---

```console
$ python test_pjo_exit_check.py
Ran 27 tests in 0.465s
OK
```

検査 27 本。採用の前に、対象を 7 通りわざと壊しました —— 太平洋時間の変換を落とす / 完全一致を前方一致に緩める /
空の機能ファイルを失敗として数える / `reporting_Baselines` の別綴りを外す / `Project_` 接頭辞を外す /
0 バイトの検出を止める / XML の属性を読まない —— そして 7 件すべてを検査が捕まえることを確かめました。
落ちるところを一度も見ていない検査は、証拠になりません。

Python 3.8+、依存なし。ライセンスはこのリポジトリと同じ MIT です。
