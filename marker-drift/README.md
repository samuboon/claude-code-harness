**日本語: [README.ja.md](README.ja.md)**

# marker-drift — the loop stopped itself. The work was done. One missing space did it.

On the morning of 2026-09-16 an unattended loop shut itself down. The reason is in the log: **three units in a row with no commit.**

Two of those three had committed. The marker was there too. The gate was matching
`(unit N)` **exactly**, and what the worker had typed was `(unit34)` — one space short. To
the gate that is not a near miss. It is a line with no marker, and a unit with no marker
is counted as a unit that did no work.

This reads the same lines the gate reads, matches the marker **exactly**, and then — only
for the lines that did *not* match — relaxes one typographic axis at a time to see whether
a slightly kinder gate would have let them through. It names the axis that did it.

```
$ python marker_drift.py --marker "(unit {n})" --git . --at end
marker      (unit {n})
lines read  917
exact       30
drift       3
no marker   884

relaxing one axis would have admitted:
  space                  3   (any run of whitespace in the marker, including none at all)

  line 11
    chore: KDP has no way to check, measured the GitHub side instead(unit34)
                                                                    ^^^^^^^^
    found '(unit34)', relaxing space
```

Standard library only. No network. Exit **0 = nothing lost, 1 = drift found, 2 = the scan
did not happen**.

---

## Measured (the private repository this runs on, 917 commits)

| gate | lines read | exact | drift | no marker |
|---|---:|---:|---:|---:|
| `(unit {n})` (anywhere on the line) | 917 | 35 | **4** | 878 |
| `(unit {n})` (`--at end`) | 917 | 30 | **3** | 884 |
| `{w}: ` (`--at start`, the commit-type prefix) | 917 | 915 | **0** | 2 |

Three things to take from that.

1. **Of the 39 lines that carried the marker, the strict gate turned away 4 — about 10%.**
   All four for the same reason: one space.
2. **One of those four was this tool's own false positive.** The commit that *fixed* the
   stop had `(unit34)` inside it as a **quotation**. Having said the marker counts
   anywhere on the line, that is the tool's error and not the writer's. With `--at end`
   (the right flag when the gate anchors at the end) it drops to 3 — and **those three are
   exactly the commits the gate really did lose.**
3. **The control row is probably the important one.** Run the same 917 subjects against
   "a `feat:`-style prefix at the head of the line" and the drift is **zero**. The words
   people type every day did not wander. What wandered was **the marker a machine decided
   to read** — the one with a number in it, copied out of an instruction each time.

---

## The five axes

| axis | what it forgives |
|---|---|
| `width` | full-width letters, digits and punctuation -> ASCII (`３４`, `ｕｎｉｔ`, `：`) |
| `bracket` | bracket shapes -> ASCII `( ) [ ] { } < >` (`（）`, `【】`, `〔〕`) |
| `dash` | dashes and the Japanese long-vowel mark -> `-` (`–`, `—`, `−`, `ー`) |
| `case` | ASCII upper case -> lower case |
| `space` | every run of whitespace in the marker becomes "any amount, including none" |

The report names the **smallest set of axes** that had to give for that line. A line with
full-width digits is not also blamed on `case`.

`space` is the one axis that relaxes the **marker** instead of editing the line. Deleting
whitespace from the line would quietly change what `--at start` means, and `xx feat: y`
would start matching a gate anchored at the head. `test_the_space_axis_never_edits_the_line`
holds that door shut.

---

## What it cannot do (read this part first)

1. **A line where the marker was never written does not appear.** One of the three stops
   that morning was exactly that: an upstream worker ran for 522 minutes and never wrote
   the marker at all. **This tool finds "nearly". It cannot find "absent".** Same symptom,
   different failure. `--list-missing N` will print lines with no marker, but it will not
   tell you which of them should have had one, because it cannot know.
2. **The space axis reaches the whitespace the marker already has, and the two sides of a
   placeholder. Nothing else.** A line like `( unit 34)` — a space where the marker has
   none — is not caught. That limit is written down as a test
   (`test_a_space_where_the_marker_has_none_is_not_caught`).
3. **It does not read meaning.** A line that *quotes* the marker mid-sentence counts as
   carrying it, by default. That is the false positive above. Pass `--at start` or
   `--at end` when your gate anchors.
4. **`{n}` and `{w}` are ASCII on purpose.** Python's `\d` matches `３` and `\w` matches
   `単`. A gate written with `\d` is *already* letting full-width digits through — and if
   the strict side of this tool used `\d`, that whole class of drift would vanish into
   "exact". The strict side has to be strict.
5. **No alternation.** "either `feat:` or `fix:`" is two runs, not one.
6. **It does not tell you what to do.** Whether to loosen the gate or to stop asking a
   writer to type the marker at all (that is the better answer) belongs to whoever owns
   the gate.

---

## Use

```bash
# commit subjects (default repository is the current directory)
python marker_drift.py --marker "(unit {n})" --git . --at end

# how much your ticket ids wander
python marker_drift.py --marker "{w}-{n}" --file CHANGELOG.md

# anything on stdin
git log --pretty=%s | python marker_drift.py --marker "(unit {n})"

# also show 20 lines that carry no marker (after reading limitation 1)
python marker_drift.py --marker "(unit {n})" --git . --list-missing 20

# from CI: exit code 1 when the gate is losing lines
python marker_drift.py --marker "{w}-{n}" --git . --max 200 --format tsv
```

**Write the marker the way the gate spells it.** Three placeholders: `{n}` (ASCII digits),
`{w}` (ASCII word), `{any}`. Everything else is a literal — this is not a regex, so `(` is
a `(`.

`--at` takes `anywhere` (default), `start`, `end`. **Pass it when your gate anchors**; it
is the difference between the 4 and the 3 in the table above.

---

## Checks

```bash
python -m unittest discover -s marker-drift -p "test_*.py"   # 85 tests
python mutation_check.py                                      # 21 deliberate breakages
```

**All 21 are caught. The first run caught 17.** Two of the four survivors were the same
shape, and that was the lesson: **the whitespace allowed before an anchored marker and the
whitespace allowed beside a placeholder were covering for each other.** Break either one
and the other still admits the line, so the suite stayed green. Two guards that overlap
mean nobody notices the day one of them dies.

(The [top-level README](../README.md) has the mirror image of this story further down —
two *instruments* that shared one blind spot, undetected until the day before publishing.)

---

## Where this came from

An AI runs a business whose goal is ten million yen of profit in twelve months. The loop
takes one unit of work each morning, writes a marker into the commit subject at the end,
and a supervisor counts those markers to decide whether anything is moving. **When the
counting side is wrong by one character, a day that moved is recorded as a day that
stopped.**

The morning it stopped, the first thing the owner said was: *"the loop has stopped itself.
why."*

日本語版: [README.ja.md](README.ja.md)
