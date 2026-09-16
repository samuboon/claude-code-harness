**日本語版: [README.ja.md](README.ja.md)**

# unbacked-numbers — the front page of this repository states 110 numbers and quotes the source for none of them

Two things happened here within a week of each other. A worker agent was sent to read a GitHub issue and count the 👍; it came back with **153**, which was every reaction on the thread added together — the `+1` count was **149**. And a claim about how a provider's account lock behaves was stated from memory, confidently, and retracted the next day.

The rule written after the first one — *numbers only from a source you can reach* — is a sentence in a policy file. A sentence does not check anything. This does:

```bash
python unbacked-numbers/unbacked_numbers.py REPORT.md
python unbacked-numbers/unbacked_numbers.py REPORT.md --min 1 --drift 2
python unbacked-numbers/unbacked_numbers.py docs/ --format paste   # counts only: no paths, no line text
```

It splits a document into **quoted evidence** — fenced blocks, block quotes, inline code, `"..."`, `「...」` — and **prose**, and lists every number in the prose that appears in no quote anywhere in the same file.

**It has no idea whether a number is true.** It answers a smaller question that is nearly free: *does this document carry the evidence for the numbers it asks a reader to believe?* For a report written by a model, which produces fluent digits at no cost, that question turns out to be the useful one.

---

## Measured, starting with the number that makes this repository look worst

```
python unbacked-numbers/unbacked_numbers.py README.md

110 unbacked numbers in 1 files
  near-miss (a quoted number is within 5%) : 0
  unbacked                                 : 107
  link-only (a URL on the line, no quote)  : 3
  below --min 10 (not counted)             : 18
  files that quote nothing at all          : 0
```

A hundred and seven are plain findings and three sit on a line that offers a link instead. Among them are the firing counts in the "Measured (no spin)" table, which is the part of that page that exists to be trusted. The evidence for them is real and sits in a ledger in a private working tree, which is to say: **not in the document**, and a stranger reading the page cannot tell those numbers from invented ones. The Japanese front page scores 129. The whole repository:

```
python unbacked-numbers/unbacked_numbers.py .

778 unbacked numbers in 31 files
  near-miss (a quoted number is within 5%) : 29
  unbacked                                 : 529
  link-only (a URL on the line, no quote)  : 220
  below --min 10 (not counted)             : 132
  files that quote nothing at all          : 8  (--strict to scan them)
```

`link-only` is its own column because a link is the most common thing offered in place of a quote, and it is not one: it is a promise that the number is at the other end.

## The three things it gets wrong, measured on this repository

**1. The near-miss column — the one I would most like to sell you — is wrong twenty-nine times out of twenty-nine here.** A number that lands within 5% of a quoted number is flagged as a possible transcription slip, because that is exactly the shape of the 153/149 mistake this was built from. On this tree every single one is noise, and I read all of them: eleven are the rank column of a data table (`abandoned-demand/MAP.md`, rows numbered 95…105 sitting beside a quoted count of 100), four are threshold prose in `tile-seam/README.md` (*100% and it is the worst edge; 99% or more without reaching 100%*), two are a texture size next to a quoted byte value one smaller — **and twelve are in this file and its Japanese twin**, including the upper bound of the year range a few lines below, which sits within 5% of a date quoted further up. The floor under the column is already `NEAR_MISS_FLOOR = 100` — below that, a 5% window is one unit wide and every small integer is a near-miss of its neighbour — and it is still wrong here. **The case it was built for exists in the test suite and not yet in the field.** `--drift 0` turns the column off.

**2. Point it at one report, not at a tree.** The private working tree this repository is generated from is 480 files of Japanese business prose, and it returns **26,971 rows** — 56 per file, which nobody will read. `--min 100` only brings it to 20,618, because the problem is not the small numbers; it is that a document written to be argued with cites its sources by link and by reference, not by quoting them inline. **On a single report it is a two-minute read. On a tree it is a wall.** That is the honest scope.

**3. A quote in the same file is not proof that the quote is real.** A model that invents a number can invent the block quote above it. This closes the gap between *a number nobody can check* and *a number with a checkable claim attached to it*, which is one step, not the whole distance. The step after it is a human opening the URL — which is why `link-only` is reported rather than silently accepted.

## How a number becomes a row

1. It sits in the **prose**, outside every quote in the file.
2. Its value appears in **no quote in the file**. Spelling does not matter: `1,200` is backed by a quoted `1200`, `１，２００` is backed by `1200`, `30000` is backed by a quoted `3万`, `8.6` needs a quoted `8.6`.
3. It is not a **name that happens to be digits**: dates (`2026-09-16`, `2026年9月16日`, `9/30/2026`, `09-16`), clock times, `v3.1`, semver, `§2`, `#3772`, `第3`, `[^12]`, commit hashes, file paths, URLs, list markers, identifiers like `IMP-45` or `x20`, and a bare `1900`–`2100` unless a unit follows it (`1980 円` is a price, `1980` is a year). `--include-years` promotes years.
4. It is **big enough to be a claim**: bare integers below `--min` (default 10) are counted and not listed. Anything carrying a unit — `7%`, `¥7`, `7 件`, `7 days`, `7.5`, `1,200` — is always listed regardless of size.
5. Files that **quote nothing at all** are skipped by default and counted in the summary, because "every number in it is unbacked" is a true and useless sentence about a file with no quotes in it. `--strict` scans them.

**A number alone in backticks is not a quote.** `184` inside a sentence is a writer emphasising their own claim; `firings=184` is a line from somewhere else. The first version did not make that distinction, and the first thing it did was launder the front page: a new paragraph there that mentioned the table's numbers in backticks turned them all into quoted evidence, and the count dropped. Inline code now counts as evidence only when it contains something other than digits and punctuation.

| flag | what it is for |
|---|---|
| `--min N` | floor under bare integers (default 10) |
| `--drift N` | percent window for the near-miss column (default 5; `0` turns it off) |
| `--strict` | also scan files that quote nothing |
| `--include-years` | treat a bare 1900–2100 as a number |
| `--exclude GLOB` | skip paths — repeatable, e.g. `--exclude 'MAP.md'` |
| `--format tsv\|paste\|github` | a table / counts with no paths or text / `::warning` annotations |

Exit codes: **0** nothing unbacked · **1** findings · **2** the scan did not happen. A scan that read zero files exits 2 rather than printing a clean report, because a green check over an empty scan is worse than an error.

```yaml
- run: python unbacked-numbers/unbacked_numbers.py reports/ --format github
```

## What it never does

No network. No dependencies beyond the standard library. It only opens files people write sentences in (`.md .markdown .txt .rst .adoc .org`) and never opens `.env`, `.pem`, `.key`, `id_rsa` or anything in that family. Before printing a line it redacts any token-shaped run of 24+ characters that looks like a credential rather than a path or a sentence; `--format paste` goes further and prints no file names, no line text and no numbers at all, so the block can be pasted somewhere public.

## Who should not bother

If your reports are generated from a dataset, or every figure in them is a footnote to a citation manager, this has nothing for you. It is for the documents where a person or a model typed a number into a sentence and everyone downstream believed it.

## Tests

```bash
python -m unittest discover -s unbacked-numbers -p "test_*.py"   # 78 tests
python unbacked-numbers/mutation_check.py                        # 22 mutations, all caught
```

`mutation_check.py` breaks the tool in twenty-two specific ways — reads `1,200` as `1`, lets the prose back itself, drops the mask that keeps dates from being counted, lets `--format paste` print the rows — and fails if the suite lets any of them through. **The first run caught 13 of 19.** Of the six survivors, two were bad mutations that did not change the tool's behaviour at all (they were replaced with ones that do), and four were missing tests, now in `Backing`, `Splitting`, `Ignoring` and `CLI`. The three mutations added afterwards all came from running the tool on this repository: a cp932 console crash, a redaction that ate ordinary Japanese prose, and the backtick hole above.

MIT. Part of [claude-code-harness](../README.md).
