**日本語: [README.ja.md](README.ja.md)**

# stated-limits — 44 ceilings in the rule files. Five of them point at anything.

A rule file governing an unattended agent loop said this, in bold, in the section on how
to publish:

> **one to three pushes per week**

The loop it governs publishes one thing per unit of work. It had been pushing six times
a day. Nobody noticed, because **nothing counts pushes** — the sentence is a ceiling
with no instrument under it, sitting in the same file, in the same typeface, as the
rules that are enforced. A limit nobody counts is not a weak rule. It is a rule that
teaches the reader which lines in that file are decorative, and the reader cannot tell
which ones those are without checking every line by hand.

`stated-limits` reads prose, pulls out the quantities a document declares as its own
ceiling, works out which files each one is talking about, measures them, and prints the
ones that are over. **Limits it cannot resolve are printed too, under the reason it
failed**, because "44 ceilings, 5 of which point at something measurable" is the
finding — not a gap in the report.

```
$ python stated_limits.py CLAUDE.md --root . --all
documents      1
sentences      7
limits found   6
  checkable    4
  unverifiable 2
breached       2

CLAUDE.md:4  30 lines BREACH  [per-file]
  actual   47 lines  (over by 17 lines)
  measured rules  -- largest of 2 files: rules/web-safety.md
  said     Each file under `rules/` is 30 lines or under.

CLAUDE.md:5  200 characters BREACH  [per-line]
  actual   203 chars  (over by 3 chars)
  measured DECISIONS.md  -- longest line is line 1
  said     One line of DECISIONS.md is 200 characters or under.

CLAUDE.md:6  60 KB UNVERIFIABLE
  reason   no-target  (the sentence names no file to measure)
  said     Keep everything that loads automatically to no more than 60 KB.

CLAUDE.md:7  3 pushes UNVERIFIABLE
  reason   unmeasurable-unit  (a ceiling on events; no file can be counted to check it)
  said     1-3 pushes per week.

CLAUDE.md:3  250 lines OK
  actual   87 lines  (under by 163 lines)
  measured STATUS.md, DECISIONS.md  -- combined: 27 + 60
  said     Layer 1 = STATUS.md / DECISIONS.md, 250 lines combined or under.
```

Standard library only. No network. Nothing is imported or executed from what it reads.
Exit **0 = nothing over, 1 = at least one breach, 2 = the scan did not happen.**
**Unverifiable is a finding, not a failure**: it will not turn your build red.

---

## Measured — the 42-document tree this came out of

| | private rule tree | this public repo |
|---|---:|---:|
| documents read | 42 | 35 |
| sentences | 6,566 | 4,924 |
| **ceilings declared** | **44** | 11 |
| …**checkable** | **5** | 1 |
| …unverifiable | **39** | 10 |
| **breached** | **0** | **1** — and it is wrong (below) |

(The right-hand column includes this page, so it moves when this page does.)

Where the 39 went: **21** were ceilings on events ("three pushes", "two documents a
week") that no file can be counted to check. **12** name no file at all. **5** name a
file that is not there. **1** names three files and never says whether the ceiling is
each or combined.

Four things to take from that.

1. **Eleven per cent of the ceilings in that tree point at anything.** Not eleven per
   cent are broken — eleven per cent can be *asked*. The rest have been read, quoted and
   obeyed-in-spirit for a month without ever having been a claim about a measurable
   thing.
2. **Zero breaches is not the good news it looks like.** Five checkable ceilings, five
   passes; the other thirty-nine were never in the running.
3. **Two of the five sit exactly on the line** — 60 lines against a 60-line ceiling, a
   longest line of exactly 200 characters against a 200-character ceiling. **Of the five,
   exactly one is counted by another tool in that tree** — a link checker that measures
   the 200-character rule on every run — and that is the one sitting at exactly 200.
   Where there is an instrument, the limit gets used to the last unit. Where there is
   none, the sentence usually never named a file to begin with.
4. **The sentence this tool was built from contains no cap word at all.** "1-3 pushes
   per week" is a bare range. Bare ranges of *event* units are read as ceilings for that
   reason. Bare ranges of measurable units are not: "lines 3-5 of the table" must never
   become a verdict about a file.

## The false positive, in full

Pointed at this repository, it reports one breach, and the breach is wrong. A sentence
in one of these READMEs says a date is only reported when a cue sits *within 40
characters* of it. Forty characters is a distance in that sentence, not a ceiling on a
file — but the clause before it named a directory, the target was carried forward, and
the tool announced that a folder of 49,742 characters was over a 40-character limit.

`--no-inherit` removes it. The same flag also drops **two real ceilings** in the private
tree from checkable to unverifiable, because those two are written as *"Layer 1 = A.md /
B.md. 250 lines combined."* — the files in one clause, the ceiling in the next.

**A sentence that looks like a limit and a sentence that is one are told apart by the
person who wrote it.** This tool guesses, and the report says which guess it made
(`[target from the previous clause]`), so you can disagree with the line rather than
with the tool.

## What it cannot tell you

- **Whether an unverifiable limit is being kept.** Twenty-one of those thirty-nine are
  about events. Checking those means logs, not files — a different instrument.
- **Whether a limit should exist.** It reads what is written and has no view on whether
  60 KB was ever the right number.
- **KB.** 50 KB is 50,000 bytes or 51,200 bytes, 2.4 % apart, and real files land between
  those two more often than you would expect. Both readings are judged by default: over
  both is `BREACH`, over one is `BORDERLINE` and does not set the exit status.
  `--kb 1000` or `--kb 1024` picks one if your rule meant one.
- **Ceilings written in a form it does not know.** It keys on a cap word (`or under`,
  `no more than`, `at most`, and the Japanese equivalents) or a bare range of events.
  "Short." "Keep it tight." "A page." are limits to a human and invisible here.
- **Numbers inside fenced code blocks.** Skipped on purpose — the numbers in an example
  are not rules — so a ceiling stated only inside a fence is missed.
- **Non-file units.** Minutes, dollars, requests per second. Not collected.

## Use

```
python stated_limits.py [PATHS...] [--root .] [--glob '*.md'] [--exclude GLOB]
                        [--self] [--kb 1000|1024|both] [--no-inherit]
                        [--all] [--json] [--rewrite-hint]
```

- `--root` — the directory bare paths in the prose resolve against. Markdown links
  resolve relative to the document they appear in, as a markdown reader would.
- `--self` — resolve "this file" / "this document" to the document the sentence is in.
  Off by default: it is a guess, and a guess that sets an exit status is worse than a
  gap in the report.
- `--all` — print the ceilings that pass. Worth doing once: a ceiling sitting exactly on
  its line is the interesting case, and it is invisible otherwise.
- `--rewrite-hint` — three before/after pairs that turn an unverifiable ceiling into a
  countable one.

In CI, run it on the files that tell your agent what it may do:

```yaml
- run: python stated_limits.py CLAUDE.md AGENTS.md .claude/rules/ --root .
```

The output is **pure ASCII by construction**, including quoted Japanese prose, which
collapses to `<JP x12>`. That is not a nicety. The tool next door in this repo exists
because a checker in this same tree finished every check and then died printing a green
circle to a cp932 console, and the gate above it read the exit status as a failure. A
report about limits must not be the thing that breaks the build.

## Tests

```
python test_stated_limits.py     # 107 tests
python mutation_check.py         # 24 deliberate mutations, all caught
```

`mutation_check.py` edits a copy of the tool in 24 specific ways — the comparison is
inverted, a combined ceiling is checked against the largest file instead of the sum, an
event ceiling is treated as measurable, a borderline size is called a breach, newlines
are transcoded so the whole report becomes one line — and reports any the suite lets
through.

**The first run caught 23 of 24, and the survivor was worth more than the 23.** The
mutation was *"treat a glob as a file to measure"*, and the test that should have caught
it passed `` `test_*.py` `` — a pattern with no slash, which never reaches the branch
the star check guards. Writing the test properly, with `` `docs/*.md` ``, failed against
the **unmutated** tool: a path-shaped glob was handing back `docs/`, so a rule about
*some* files in a directory was being checked against *all* of them. One line of
lookahead, and a bug that would have been reported as a confident breach.

Every test asserting a breach has a partner asserting the same shape does *not* breach.
That mattered too: the borderline branch shipped with a broken format string, and every
borderline test stopped at the scan without rendering a report, so the tool crashed on
the first real borderline file. The test that renders one now exists.

## Licence

MIT. Part of [claude-code-harness](../README.md) — tools that came out of running an
unattended agent loop, kept because the loop broke on them first.
