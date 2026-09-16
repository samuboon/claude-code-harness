**日本語版: [README.ja.md](README.ja.md)**

# prose-expiry — the deadlines that only exist as a sentence somebody typed once

Its sibling [`key-expiry/`](../key-expiry/) reads the only two kinds of credential that carry their own death date inside them — a JWT's `exp`, an X.509 `notAfter` — and then says, correctly, that it can tell you nothing about the rest.

**This is the rest.** End of support. A contract renewal. A migration cut-off. A certificate somebody else holds. A trial that turns into an invoice. Almost every deadline a team actually has was written down exactly once, in a sentence, in a README or a ticket or a table cell or a comment above a constant — and after that day nothing ever reads the sentence again.

```bash
python prose-expiry/prose_expiry.py .                    # the whole tree
python prose-expiry/prose_expiry.py . --within 30
python prose-expiry/prose_expiry.py . --format paste     # counts only: no paths, no line text
python prose-expiry/prose_expiry.py . --ledger EXPIRY.tsv
```

On this repository, on 2026-09-16, with its own test fixtures excluded:

```
6 written expiry dates over 3 distinct dates in 58 files, read on 2026-09-16
  already passed : 0
  within 90      : 6
  later          : 0
  weak cues not counted: 5  (--include-weak to see them)
  a date nobody wrote down is not here. That is what EXPIRY.tsv is for.
```

Six rows took under a minute to read, and one of them — `pjo-exit-check/README.ja.md:5`, *Project Online は 2026-09-30 で提供終了します* — is a real deadline that will make a directory in this repository worthless on the day it passes.

---

## The three things it gets wrong, measured on this repository

**1. The default window missed the deadline this repository was built around.** The English file says:

```
Project Online retirement : 9/30/2026 8:00:00 AM Pacific Time (= 2026-09-30 15:00 UTC)
```

Fifty characters separate the word *retirement* from the ISO date, and the default `--near 40` refuses to connect them. The Japanese file, which writes 提供終了 next to the date, was found. `--near 80` finds both, and takes the count from 6 rows to 9. **A tool that reports a miss it made on its own author's file is more useful than one that doesn't, so this is the first section rather than a footnote.**

**2. On a prose-heavy tree it is noisy, and that is not fixable with a longer word list.** The private working tree this repository is generated from is 677 files of Japanese business documents whose *subject* is deadlines. It returns:

```
985 rows over 124 distinct dates
  already passed : 276  (oldest by 17539 days)
```

The oldest row is from 1978 — a sentence about a shop closing in 2026 that mentions, thirty characters away, the day it opened in 1978. The word 満了 is in the sentence; it is about a different date. On that tree `--near 12` cuts 985 rows to 602 without losing the real ones, and `--exclude` is the other half of the answer. **The honest summary is: on a tree that talks about dates constantly, the precision of a word list is poor, and no amount of tuning makes it good.**

**3. A date nobody wrote down is invisible here.** This is the limit that no version of this tool will fix, and it is the whole reason [`EXPIRY.tsv`](EXPIRY.tsv) exists: five columns, empty, for the deadlines that live in your head or in somebody's inbox.

```
kind    date    what_stops    how_you_found_out    days_late
```

`--ledger EXPIRY.tsv` merges those rows into the same report, sorted with the rest. The fourth and fifth columns are not decoration — *how you found out* and *how late you were* are the only two facts that say whether a deadline is a problem or an inconvenience, and they are the ones nobody records.

## How a date becomes a row

1. The line contains a real calendar date — `2026-09-30`, `2026年9月30日`, `September 30, 2026`, `30 Sep 2026`. `2026-02-30` is not one, and neither is `2026-09/30`.
2. An **expiry cue** sits within `--near` characters of it, on the same line, or in the Markdown heading up to five lines above. Strong cues are the ones a reader would accept without context: `EOL`, `end of support`, `expires`, `deadline`, `sunset`, `deprecated`, `retire`, `valid until`, `discontinued`, `期限`, `提供終了`, `失効`. Weak cues — `due`, `until`, `renew`, `migrate`, `更新` — are counted and reported at the bottom but not listed, because a changelog uses them about the past as often as a plan uses them about the future. `--include-weak` promotes them.
3. Every row names the cue that matched, so you can see *why* the tool thought it was a deadline and overrule it.

| flag | what it is for |
|---|---|
| `--within N` | the window in days (default 90) |
| `--near N` | how close the cue must sit to the date (default 40) |
| `--include-weak` | add `due` / `renew` / `更新` and their kind |
| `--exclude GLOB` | skip paths — repeatable, e.g. `--exclude 'test_*'` |
| `--ledger FILE` | add the dates no file contains |
| `--today YYYY-MM-DD` | ask what had already passed on some other day |
| `--format tsv\|paste\|github` | a table / counts with no paths / `::warning` annotations |

Exit codes: **0** nothing has passed and nothing is inside the window · **1** something is · **2** the scan did not happen. A scan that read zero files exits 2 rather than printing a clean report, because a green check over an empty scan is worse than an error.

```yaml
- run: python prose-expiry/prose_expiry.py . --within 30 --format github
```

## What it never does

No network. No dependencies beyond the standard library. It only opens files people write sentences in, and never opens `.env`, `.pem`, `.key`, `id_rsa` or anything in that family. Before printing a line it redacts any run of 24+ characters that looks like a credential rather than a path — `--format paste` goes further and prints no line text and no file names at all, so the block can be pasted somewhere public.

## Who should not bother

If your deadlines already live in a calendar, a ticket tracker with due dates, or a renewals spreadsheet somebody owns, this has nothing for you. It is for the deadlines that were written into prose because there was nowhere else to put them.

## Tests

```bash
python -m unittest discover -s prose-expiry -p "test_*.py"   # 50 tests
python prose-expiry/mutation_check.py                        # 18 mutations, all caught
```

`mutation_check.py` breaks the tool in eighteen specific ways — reads the day as the month, drops the proximity rule, prints a green check over a scan that read nothing, lets `--format paste` leak the line it matched — and fails if the suite lets any of them through. Two of the eighteen survived the first run; the two tests that now catch them are in `Cues` and `Ledger`.

MIT. Part of [claude-code-harness](../README.md).
