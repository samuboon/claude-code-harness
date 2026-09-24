**日本語: [README.ja.md](README.ja.md)**

# table-total-check — Llama 2's model card lists three models and a total for four

The carbon table in `meta-llama/llama`'s MODEL_CARD.md has rows for Llama 2 7B, 13B and 70B, and a
**Total** of 3,311,616 GPU hours and 539.00 tCO2eq. The three rows add up to 2,273,280 and 385.08.
The Llama 2 paper's version of the table has a fourth row — **34B: 1,038,336 GPU hours, 153.90
tCO2eq** — which is exactly the difference. The card dropped the row and kept the total, and
`microsoft/Llama-2-Onnx` copied the card.

Nobody re-adds a table they are reading. The `**Total**` row is bold, it sits where totals sit, and
it is believed. In `airbnb/mavericks`' sample README the `mvp-clean` column is 0 + 2,777 + 608 and
its Total says 2,385; the rows make 3,385. A design doc in `eshu-hq/eshu` lists 64 directories under
a total of 368 / 713; they come to 370 / 714.

`table_total_check.py` re-adds them. It finds the Markdown tables in a file, the rows labelled
Total / Subtotal / Grand total / 合計 / 小計 …, the columns headed Total, and the percentage columns
under a total, recomputes each from the numbers it can read one way only, and lists the ones that
disagree.

```bash
python table_total_check.py README.md
python table_total_check.py docs/              # every .md / .markdown / .mdx below
python table_total_check.py docs/ --why        # also: each cell it did not judge, and why
python table_total_check.py docs/ --json
```

On today's `main` of three of the repositories above (2026-09-24):

```
$ python table_total_check.py llama/MODEL_CARD.md
MODEL_CARD.md:50: error TOTAL  "Time (GPU hours)", Total row: the total says 3,311,616; the 3 rows above add up to 2,273,280 (+1,038,336)
MODEL_CARD.md:50: error TOTAL  "Carbon Emitted(tCO 2 eq)", Total row: the total says 539.00; the 3 rows above add up to 385.08 (+153.92)

$ python table_total_check.py mavericks/sample-todo/README.md
sample-todo/README.md:16: error TOTAL  "mvp-clean", Total row: the total says 2,385; the 3 rows above add up to 3,385 (-1,000)
```

(385.08 + 153.90 = 538.98, which rounds to the table's 539.00 within the two decimals each row is
shown to.)

Standard library only. It reads files; it runs nothing, writes nothing and sends nothing
(`replay_fixes.py` below is the one part that reads from GitHub). Exit code 1 when there is an
error, 0 otherwise.

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `TOTAL` | error | A row labelled Total / Sum / Grand total / Subtotal / 合計 / 小計 / 計 … does not equal the rows above it (or below it, when the only total row comes first). Subtotals are not added in twice: a grand total may equal the data rows or the subtotals. |
| `TOTAL?` | warning | The same, but some of the rows are blank (`—`, `-`, `n/a`), which may be the difference. |
| `ROWTOTAL` | error | A column headed Total does not equal the columns next to it, on a row where most rows of the table do. Which columns it adds up is found from the table (the run of numeric columns next to it that most rows agree with), not assumed; with fewer than two agreeing rows it judges nothing. |
| `SHARE` | error | A percentage column under a total, on a row where it is not count ÷ total while most rows are. |

**Compared exactly:** whole numbers and money (`$10.00 + $5.50` is `$15.50`, not `$15.49`).
**Allowed their rounding:** decimals, percentages and measurements (`ms`, `MB`, `h` …) — n parts
shown to one decimal may drift by n × 0.05 — and whole numbers that all end in 000, which are
read as rounded to their last non-zero digit (OpenAI's evals README shows 19,850,000 + 80,000 as
19,940,000; that is three significant figures, not an error).

**Accepted as not a sum:** a total that is the mean, median, max or min of the rows, or a mean
weighted by another column (a pass rate under Passed / Run). A total of percentages that add up
past 100 % (accuracy rates under a "subtotal") is left alone as "rates, not shares".

**Rows it reads as totals:** the label must be the word, give or take bold, a colon and a
parenthesis (`**Total (16 Agents)**`, `合計(税込)`). `Total time` is not a total row.
`Batch 1 Subtotal` is a subtotal. `COMPONENTS MERCHANDISE TOTAL` is a *named* total: if the rows
directly above it add up to it, it stands for them in the grand total; if not, it is a line of its
own (a BOM's "PCB merchandise total" is a price, not a sum). Rows that begin with Average / Avg /
Mean / Median / Max / Min are not added.

**Never guessed — counted as not judged, and listed with `--why`:** text among the numbers
(`3 (est.)`), `~120`, `100+`, a struck-through value, mixed units (`900 KB` next to `1.2 MB`), a
`...` row (rows were left out), `1.429` under whole numbers (1,429 written with a dot, or a
decimal), a total cell that is not one number (`$1,319.81 PC only / $1,459.80 with monitor`).
Columns headed Year / Version / Rank / # / ID / Date, and anything left of the label column, are
names, not quantities.

**Read:** GitHub-flavoured pipe tables; `1,234.5`, `1 234`, `1.234,5` (when the column writes
decimals with a comma), `(20)` as −20, `$` `€` `£` `¥` `₹` and currency codes (`IDR1,194,606`,
`94.22 USD`), `%`, links and code ticks in cells, escaped `\|`. Fenced code and HTML comments are
skipped. HTML `<table>`s, reStructuredText and AsciiDoc are not read.

### In CI

```yaml
# .github/workflows/tables.yml
on: pull_request
jobs:
  tables:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: curl -fsSLO https://raw.githubusercontent.com/samuboon/claude-code-harness/main/table-total-check/table_total_check.py
      - run: python3 table_total_check.py .
```

This has not been run on GitHub by us.

---

## Measured

Everything below is reproducible with `replay_fixes.py`. The first version of the checker was
frozen before any real table was read; each set was split in two **before tuning**, and the held
out half was run on the frozen version first.

### 1. Public commits that corrected a total

GitHub's commit search, 38 queries (`fix total`, `correct totals`, `fix table arithmetic`,
`does not add up` … — listed in `QUERIES`), gave **4,566 commits**. From the diff and the file
alone, before the checker ran, **6** changed only a total — a Total row or a Total column, only in
its numbers, with the rows it adds up untouched, so the old total was wrong by construction. Most
"fix total" commits are code. Split by commit id:

| | frozen first version | final |
|---|---|---|
| held out (3) | caught 1 · partly 1 · missed 1 | the same |
| tuning (3) | partly 1 · missed 2 | caught 1 · partly 1 · warned 1 |

- **caught** — `ernestngenest/nez-harness`: skill counts 128 where the 13 rows make 131, flagged
  before the fix and gone after it.
- **partly** — `Juwan-Hwang/moon-certified`: flagged before (3,291) and still after (3,365); the 111
  rows add up to 1,481 either way, and the file does not say what else the total counts.
  `abhinay-sambherao/HeatScanAI`: the fix moved the hours total from 443 to 408; the 33 rows make
  406 (added up again by hand).
- **missed** — `clankanoid/gaming-pc-build-2026`: the total cell is a sentence
  (`$1,319.81 PC only / $1,459.80 with monitor`). Not judged, by design.
- The tuning half taught: a total over a single row (was skipped), and currency codes
  (`IDR1,194,606`). The one left at **warned** has four blank rows.

Six is a small number, and it is what the search gives.

### 2. Commits that changed the rows and the total together

The same search gave **61 commits** that edited a table with a total together with its rows. Nothing
says those tables were wrong, so every error after the commit is either a false alarm or a mistake
the commit left in. Every one was read by hand.

| | frozen first version | final |
|---|---|---|
| held out (30) | 7 flagged: **3 real, 4 false** | 3 flagged: **3 real, 0 false** |
| tuning (31) | 3 flagged: 0 real, 3 false (and 1 real one missed) | 2 flagged: **2 real, 0 false** |

The five real ones, each re-added by hand: `cloudshare360/aws-cloud-engineer-with-nodejs` (course
hours 83.0; the nine sections make 84.0), `eshu-hq/eshu` (368 / 713 for 370 / 714),
`JasonMomanyi/EO-AI_Crop_Intelligence_Platform` (ESA funding 47,000; the five tasks make 47,500),
`Rabieulawal/alarmpcb` twice (a BOM whose merchandise total was not the parts above it; later its
grand-total quantity 251 for 250).

The false ones in the first version, and what changed: `1.429` read as a decimal under whole
numbers (three commits of one project — now not judged); rates under a Chinese 小计 row added as if
they were shares (now "rates, not shares"); `Batch 1 Subtotal` and `COMPONENTS MERCHANDISE TOTAL`
not recognised, so the grand total counted everything twice (named totals, above). The real one the
first version missed was EO-AI's 47,000: it was "explained" as the difference of two other totals
(53,000 − 6,000). That explanation — and the ratio one next to it — was taken out; a weighted mean
covers the honest cases of both.

### 3. Well-known repositories, today

GitHub code search for `Total` in Markdown under 30 organisations (microsoft, google, facebook,
apache, kubernetes, rust-lang, aws, grafana, openai, huggingface, pytorch, JetBrains, airbnb, uber
…) gave **2,787 files**, halved by a hash of repository and path before anything was read. **63**
have a table with a total.

| | frozen first version | final |
|---|---|---|
| held out (1,362 files, 34 with a total) | 4 errors: **3 real, 1 false**; 3 warnings, all false | 3 errors: **3 real**; 0 warnings |
| tuning (1,425 files, 29 with a total) | 9 errors, 2 warnings | 3 errors: **3 real**; 0 warnings |

Real: the Llama 2 card (two columns, both copies), mavericks' `mvp-clean`, a timing table in
`JetBrains/intellij-community`'s python-lsp-core README (4,010 ms over steps of 3,000 + 557, and
1,200 ms under a single step of 1,789), and `uber/tango`'s bytes-per-node column (18.5; the eight
columns make 19.40 — and 52.25 MB over the node count that gives 8.00 B/node for HASH is 19.4).
False in the first version: OpenAI's rounded token counts (above), and pytorch/executorch's tables
with `...` rows, which were warned about instead of being left alone.

Over all 2,787 files the final version re-added **238 sums: 227 add up, 6 do not, 5 are not sums**
(a mean, a max). It left **39** things alone, most of them a Total column with no numeric columns
next to it (14) or a total cell that is not one number (12).

**What is not measured:** recall on tables nobody has fixed — the 63 files are what exists, not a
sample with known errors. A total written in prose ("the total is 42") is not read at all.

### 4. On this repository

```
$ python table-total-check/table_total_check.py .
62 files, 134 tables: 0 total rows, 0 total columns, 0 percentage columns; 0 sums checked, ...
0 errors, 0 warnings
```

It has nothing to say about us: none of our 134 tables has a total. That is the honest result, not
a clean bill.

### Tests

`python -m unittest test_table_total_check` — 57 tests, several named after the public file that
taught them. `python mutation_check.py` breaks the checker 45 ways, one at a time (a subtotal added
twice, 1.429 read as a decimal, `AVG-001` read as an Average row, whole numbers given rounding slack
…) and checks the suite fails each time: **45 of 45**. The first run caught 25 of 33: one pattern
was stale, four survivors were holes in the tests (one hid a real bug — a total one more than the
largest row was accepted as "the max"), and three were checks that could never fire, which were
taken out or rewritten.

## Files

| File | |
|---|---|
| `table_total_check.py` | the checker |
| `replay_fixes.py` | `--search` / `--classify` / replay of `FIXES` and `UPDATES` / `--files` for files pinned at a commit / `--lines` to read the table yourself |
| `test_table_total_check.py`, `mutation_check.py` | the tests, and the check that they can fail |

MIT, like the rest of this repository.
