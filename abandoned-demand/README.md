**日本語版: [README.ja.md](README.ja.md)**

# abandoned-demand — 35,206 thumbs-up on requests that will never be built

A maintainer closes an issue as `not planned`. The request does not stop existing; it stops
being tracked. This directory is a 345-line script, standard library only, that finds those
requests and ranks them by **how many people asked for them**.

**The current list is [MAP.md](MAP.md): 108 requests, 35,206 👍, regenerated 2026-09-15.**

```console
$ python abandoned_demand.py collect --min-reactions 100 --out MAP.md
wrote MAP.md (108 rows kept, 13 dropped for having fewer than 100 thumbs-up)
```

The top of today's list, unedited — including the two rows that are jokes, because filtering
them would mean substituting our judgment for the count:

| # | 👍 | Repository | Request |
|--:|--:|---|---|
| 1 | 1,430 | `microsoft/TypeScript` | Suggestion: `throws` clause and typed catch clause |
| 2 | 1,139 | `microsoft/TypeScript` | Suggestion: Range as Number type |
| 3 | 1,046 | `rust-lang/rust` | Rust is Beautiful *(a joke issue)* |
| 4 | 881 | `microsoft/TypeScript` | Suggestion: minification |
| 5 | 811 | `NixOS/nixpkgs` | Package request: Zen Browser |
| 6 | 763 | `flutter/flutter` | Let flutter be installable via homebrew |
| 7 | 739 | `element-hq/element-web` | Support for multiple matrix accounts |
| 8 | 670 | `Xerasin/GCinemaCraftDownloader` | 0w0 *(a joke issue)* |
| 9 | 662 | `microsoft/appcenter` | Flutter Support |

---

## The one thing this does that a search box does not

**GitHub cannot sort or filter by 👍.** The `reactions:` qualifier and the count in the UI are
`reactions.total_count`, which adds 👍 😄 🎉 😕 ❤️ 🚀 👀 and 👎 together. So the ranking you get
from the obvious query is not a ranking of demand — it is a ranking of *attention*, and the
two come apart exactly where it matters:

| Issue | 👍 (`+1`) | `total_count` | by 👍 | by total |
|---|--:|--:|--:|--:|
| `microsoft/TypeScript#13219` | **1,430** | 1,903 | **1st** | 2nd |
| `rust-lang/rust#100000` ("Rust is Beautiful", a joke issue) | 1,046 | **3,011** | 3rd | **1st** |

This tool reads `reactions["+1"]` and nothing else. Because that one line is the whole point,
it is guarded three ways: a `self-check` subcommand, 6 unit tests, and a mutation (`M1`) that
must make the suite fail.

**Measured today:** of the 121 rows GitHub returned for `reactions:>=100`, **13 did not have
100 👍**. They were on the list only because people argued in them. The script drops them and
says so in the output header.

## Everything in here, and what it is for

| File | Size | What |
|---|--:|---|
| `abandoned_demand.py` | 345 lines | fetch, dedupe, rank, render. No dependencies. |
| `test_abandoned_demand.py` | 42 tests | unit tests, no network (the fetcher is injected) |
| `mutation_check.py` | 17 mutations | breaks the tool on purpose, checks the tests notice |
| `MAP.md` | 108 rows | the current output |

```console
$ python test_abandoned_demand.py      # 42 tests, no network
$ python mutation_check.py             # 17 of 17 mutations caught
$ python abandoned_demand.py self-check
```

## How we know the tests bite

A suite that has never been seen failing is decoration. `mutation_check.py` edits the tool in
seventeen specific ways — count `total_count`, sort ascending, dedupe on issue number alone,
keep the issue body, stop escaping pipes, never stop paging — and reports any mutation the
suite lets through. **17 of 17 are caught.** It restores the original in a `finally` block.

That number was **11 of 12** on the first run. The mutation that survived was "stop replacing
`\r\n` with a space", and the reason it survived is that the next line already folded all
whitespace: the replace was dead code. We deleted the line instead of writing a test for it.
(While building the runner, two earlier throwaway versions crashed and left the tool mutated
on disk — which is why the shipped one restores in `finally`.)

## What this does not read

Issue bodies and comments are text written by strangers, and this tool is meant to be run by
an agent. It keeps **six fields per issue** — repository, number, title, 👍, closed date, URL —
and `extract()` drops everything else at the door. Two of the unit tests and mutation `M7`
exist only to keep it that way. Titles are escaped before they enter the Markdown table
(pipes, angle brackets, newlines), so a crafted title cannot break out of its cell.

**A title is not allowed to talk to the reader either.** The title is still a stranger's text,
and this file is written to be read by agents, so words that would read as an order to whoever
opens it are cut out and shown as `[...]` — the link still goes to the untouched original. We
did not think of this: our own pre-publish gate refused the first generated map, because one
row's title contained such a word. It was an ordinary feature request, not an attack
(`Ability to override/[...] sub-dependencies` in `python-poetry/poetry`), which is exactly why
the rule has to be mechanical. On the current run it fired **once**, and the header says so.

Network access is `api.github.com` only. The token, if you set `GITHUB_TOKEN`, is read from
the environment and sent in a header — never placed on a command line.

## Limits, in plain terms

- **This is run 1.** The header says "monthly" is the intent; it has been generated once. No
  one has used it for anything yet, and **the repository it lives in has 0 stars**.
- **It is a sample, not a census.** The two queries match **408 issues**; a default run pages
  in 122 of them (3 pages × 100, per query, minus the overlap). `--max-pages 10` widens it to
  the search API's hard cap of 1,000 per query.
- **The `Reason` column is GitHub's `state_reason`, and it lies a little.** Rows found by the
  `wontfix` *label* often carry `completed`, because the maintainer closed them as done and
  labelled them anyway. The label query is still the right net — it catches the repositories
  that use a label instead of the close reason — but the column is not a clean verdict.
- **Joke and meta issues get in** — two of them are in the top nine above. Filtering them
  would mean publishing our own judgment of which requests are real, so we don't; the input
  is mechanical and so is the output. Read the list, don't trust it.
- **👍 is not demand.** It is the cheapest possible signal of demand, costing one click from a
  person who was already reading the issue. Old issues have had more years to collect them.
- **No rate-limit backoff.** Unauthenticated search allows 10 requests/minute and the default
  `--sleep 2` stays under it; if you raise `--max-pages` past 5 without a token you will get an
  HTTP 403 and the script will say so and stop.

## Who it is for

People deciding what to build next, and agents doing the same on their behalf. A request that
811 people wanted, that the people closest to the code have formally declined to build, is a
different kind of signal from a feature idea — someone already measured the demand, in public,
and then the door closed.

MIT. Part of [claude-code-harness](../README.md), a set of tools measured on a Claude Code
project that runs unattended.
