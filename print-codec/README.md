**日本語: [README.ja.md](README.ja.md)**

# print-codec — every check passed. The green circle is what killed it.

A link checker in an unattended loop finished its work on the morning of 2026-09-16.
Nothing was broken. It then printed the summary line, and died there:

```
UnicodeEncodeError: 'cp932' codec can't encode character '\U0001f7e2' in position 106
```

Exit status 1. The gate above it reads exit statuses, so what it recorded was **the check
failed** — and there is nothing in a `1` that distinguishes *"seven links are broken"*
from *"the reporter fell over on its own punctuation"*. The tree was clean. The run was
counted as a failure.

`print-codec` reads Python source **without running it**, collects the string literals
that reach stdout and stderr, and names the characters a given console codec refuses.
Files that pin their own output encoding first are reported as **protected** and are not
counted at risk.

```
$ python print_codec.py tools/ --codec cp932
codec          cp932
files read     63
protected      20
at risk        2 file(s)
lines          4
characters     2 distinct

tools/linkcheck.py  (decides an exit status)
  line 161   print
    print("checked {} links / broken {} / ... / ISSUES <U+1F7E2> {} rows left"
    U+1F7E2 LARGE GREEN CIRCLE
```

Standard library only. No network. Nothing is imported from the files it reads.
Exit **0 = nothing at risk, 1 = something is, 2 = the scan did not happen**.

---

## Measured — the 63-file private tree this came out of

| `--codec` | files read | protected | at risk | lines | distinct characters |
|---|---:|---:|---:|---:|---:|
| `cp932` (Japanese Windows console) | 63 | 20 | **2** | **4** | 2 |
| `utf-8` | 63 | 20 | 0 | 0 | 0 |
| `ascii` | 63 | 20 | **20** | **110** | 310 |

Four things to take from that.

1. **Two of the four lines it named are the ones that actually stopped the loop.** The
   prediction was checked by running it: with the console pinned to cp932, the file the
   tool pointed at dies at the line the tool pointed at, with the message quoted at the
   top of this page — **down to `position 106`**.
2. **The other two are the same landmine, not yet stepped on.** `harness_size.py` prints
   `U+2717 BALLOT X` twice, and it is a file that decides an exit status. The morning it
   is first run on a Japanese console, it will tell the gate the same lie.
3. **The control row is the interesting one.** Two days earlier, on 2026-09-14, a
   different file in the same tree had died the same way on an em dash, and was fixed
   **individually**. That file comes back `protected`, 0 rows. One tree, one bug, fixed
   on one side and open on the other — nobody had looked for the other side.
4. **The `ascii` row is this tool's limit on display.** Point it at the wrong codec and
   the whole tree turns red: every Japanese string literal in those 63 files is a hit.
   **The tool does not know what your console is.** You pass `--codec`; if you pass the
   wrong one, you get 110 confident, useless lines.

## The report has to survive its own rule

A report about characters the console cannot print must not print them. Quoting the
offending source line back at you verbatim is exactly how this tool would die of the bug
it reports — so every quoted line and path goes through a replacement first, and you see
`<U+1F7E2>` where the character was.

Checked the same way as everything else here: with the console pinned to cp932, running
it on that tree prints all 27 lines of its report and exits 1. The four characters it is
complaining about never reach the stream.

## What it cannot tell you

- **Anything assembled at runtime.** The gaps in an f-string, values in variables,
  arguments. It reads the literal halves only. Module-level `NAME = "..."` is followed one
  level deep, and a name assigned twice is dropped rather than guessed at.
- **Whether `logging` output reaches a console.** That depends on handlers, so logging is
  off by default; `--include-logging` turns it on and accepts the false positives.
- **Whether "protected" means readable.** Protection is detected as text —
  `reconfigure(...)`, `TextIOWrapper(sys.stdout.buffer...)`, `PYTHONIOENCODING`. Pinning
  UTF-8 on a cp932 console stops the exception; it does not make the character legible.
  It buys you a mojibake summary instead of a false failure, which is the trade you want.
- **Your actual console code page.** Windows Terminal, `cmd.exe`, a CI runner and a pipe
  are four different answers on one machine.
- **Non-Python.** Shell scripts, Node, Go — same bug, not this tool.

## Use

```
python print_codec.py [PATHS...] [--codec cp932] [--all] [--json]
                      [--include-logging] [--exclude GLOB] [--fix-hint]
```

- `--codec` — anything Python has a codec for. Default `cp932`; `ascii` is the strictest
  useful setting if your output must survive a POSIX locale with no UTF-8.
- `--exclude` — repeatable glob, matched against both the file name and the posix path.
  `--exclude "test_*.py"` is the usual one: test files hold broken text on purpose.
- `--fix-hint` — prints the three lines that end the whole class of problem:

```python
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except AttributeError:  # Python < 3.7
        pass
```

In CI, run it on the scripts whose exit status something else believes:

```yaml
- run: python print_codec.py tools/ --codec cp932 --exclude "test_*.py"
```

## Tests

```
python test_print_codec.py        # 106 tests
python mutation_check.py          # 24 deliberate mutations, all caught
```

`mutation_check.py` edits a copy of the tool in 24 specific ways — the checker calls an
unencodable character encodable, the report quotes the source line verbatim, `--exclude`
is ignored, a protected file still sets the exit status — and reports any the suite lets
through. **The first run caught 23 of 24.** The survivor was *"return findings in
whatever order the walk produced"*: `ast.walk` happens to be near line order for simple
files, so the existing test passed. The test that catches it now puts a `print` inside a
function above a `print` at module level, where the walk returns them backwards.

## Licence

MIT. Part of [claude-code-harness](../README.md) — tools that came out of running an
unattended agent loop, kept because the loop broke on them first.
