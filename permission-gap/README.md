**日本語版: [README.ja.md](README.ja.md)**

# permission-gap — four different things stop an unattended agent, and 124 of our 233 stops were our own code

We run Claude Code unattended on a loop. When a call is refused, the model gets a string
back and keeps going, and at the end of the week you have no idea what actually stopped
it. So we counted. **335 transcript files, 20,294 tool results, 3.0 seconds of scanning,
233 refusals** (2026-09-17, one project, our own logs):

| Who said no | Refusals | Most refused shape | What you do about it |
|---|---:|---|---|
| **our own PreToolUse hook** | **124** | `python - <heredoc>` (20) | it's our code, we can fix it |
| **the platform's permission classifier** | **52** | `mcp__chrome-devtools__evaluate` (5) | not ours — but 86% of ours cleared on a later attempt, [see below](#we-said-route-around-the-classifier-then-we-put-a-clock-on-it-and-54-of-63-cleared) |
| **our allowlist didn't cover it** | **49** | `rm -rf <path>` (18) | one line of config |
| **a human clicked no** | **8** | five different shapes, once each | a conversation |

All four arrive at the model as the same kind of error on the same kind of call. A single
"failures" count — which is what a log gives you — sends you to the wrong one of those
four columns three times out of four. **In our case the biggest source of friction was
the defence we wrote ourselves**, and we did not know that until we split the column.

```
python permission_gap.py scan
python permission_gap.py scan --since 2026-09-01 --settings .claude/settings.json --json
```

Reads the session transcripts Claude Code already writes under `~/.claude/projects`.
**Standard library only, reads only, writes nothing.** Exit code 0 means it scanned
(findings are not failures); 2 means it found nothing to read.

---

## The platform gave nine different reasons, and 29 of 52 were no reason at all

The classifier's refusal string carries a tag. Ours, over 15 days:

| Reason string | Times |
|---|---:|
| `Blocked by classifier` (no tag at all) | **29** |
| `[Self-Modification]` | 6 |
| `Stage 2 classifier error - blocking based on stage 1 assessment (usually transient)` | 5 |
| `[Create Public Surface]` | 4 |
| `[Out-of-Place Publication]` | 3 |
| `[External System Writes]` | 2 |
| `[Security Weaken]` / `[Remote Repoint]` / `[Auto-Mode Bypass]` | 1 each |

Six of those nine tags landed on **the same intent** — publishing something to our own
public repository. Knowing that took a tally; from inside any one turn it looks like six
unrelated failures.

## Flapping: the same shape ran 1,657 times and was refused 27 times

The tool reduces each call to a **shape** (`cd /x && python tools/gh_api.py post /r b.json`
→ `python gh_api.py post <path>`) and then asks whether a shape that was refused has ever
run. Ours:

| Shape | Refused | Ran | Layers that refused it |
|---|---:|---:|---|
| `python - <heredoc>` | 27 | 1,657 | all four |
| `python -c <code>` | 12 | 541 | hook, classifier, human |
| `echo <arg>` | 14 | 554 | hook, classifier, allowlist |
| `Edit .md` | 7 | 1,086 | hook, classifier |
| `WebFetch booth.pm` | 5 | 15 | hook |

**A verdict that changes for the same shape is not a rule, it's a coin toss**, and an
agent that retries it looks stubborn when it is actually being rational. The opposite
case is worth naming too — **walls**, refused three or more times and never once run:
`rm -rf <path>` (20), `rm -rf <arg>` (9), `powershell -NoProfile -Command <code>` (7),
`curl -s <url>` (3). Those four are settled: stop writing them.

## We said route around the classifier. Then we put a clock on it, and 54 of 63 cleared

The table above pairs a shape's refusals with its runs, and a count has no direction.
A shape that ran a hundred times last week and has been refused ever since looks
identical to one that was refused once and worked on the retry. Those are opposite
situations and we had been reading them as one. So we asked a narrower question of the
same transcripts: **after this particular refusal, did the same shape ever come back
clean, and how long later?**

Re-scanned five hours after the headline above, so the denominators differ:
350 files, 21,438 tool results, **258 refusals**. The table below is the
`AFTER THE REFUSAL` block of `python permission_gap.py scan --dir <your project's
transcript folder>` — run it and the same four rows come out for your own logs, which
is the only reason any number on this page is worth reading.

| Who said no | Refusals | Same shape came back clean | Never did | Wait: min / median / max |
|---|---:|---:|---:|---|
| our own PreToolUse hook | 133 | 96 (72%) | 37 | 0.0 / 2.5 min / 3.1 days |
| **the platform's classifier** | **63** | **54 (86%)** | **9** | 0.0 / **11.5 min** / 23.2 h |
| our allowlist | 54 | 9 (17%) | 45 | 0.1 / 0.3 min / 1.4 days |
| a human said no | 8 | 6 (75%) | 2 | 1.0 / 17.1 min / 11.3 h |

**The row we had written "not ours, route around it" against is the row that clears
most often.** The row that does not clear is our own allowlist — 45 of 54 refusals
there were still refused at the end of the window, because a config nobody edits stays
the way it was. The layer we had filed as permanent is mostly a wait; the layer we had
filed as one line of config is the one that actually stops you until someone types
that line.

Two things keep this from being "just retry". First, **56 of those 63 refusals were of
a shape that had already run before** — so what we measured is mostly the instability
already named as flapping, seen from the other side, not a locked door opening. Second,
**7 were never attempted again in any form**, which is the failure mode this column was
built to catch: the agent read "denied" as "cannot", dropped the work, and nothing in
the log distinguished that from a real wall. It cost us two days of output sitting
undelivered behind a refusal we never re-sent.

The shapes that really were settled are the ones in the walls list, and the classifier
contributes exactly one: `python gh_api.py post <path>`, refused 3 times across two
days and never once run. **That is what a wall looks like when you have the clock —
a layer is not a wall, a shape is.**

## 36 times, an unrelated call was refused within two minutes of a refusal

Counted as `collateral`: a *different* shape, same session, refused within the window
(120s by default). We noticed this by hand first — a refusal, then a plain `grep` refused
right after, then recovery by doing the same work with another tool. **36 is not proof of
a causal link and the tool says so in its own output.** It is the number to look at before
you go hunting for a bug in your own hook.

## The measurement that came out zero, and why that is the finding

The tool cross-checks every refusal against your own `permissions.allow` rules, to catch
**the case where your config says yes and the call was refused anyway.** For us that came
out **0, against 3 allow rules.** Not because it never happened — it happened five times
in two days — but because the permission we were relying on **lived in a design document
we wrote for ourselves, not in `settings.json`.** The instrument can only see config.

A permission that exists only in prose does not run. That cost us five attempts across
two days before we accepted it, and the zero in this field is the cleanest statement of
it we have.

## What we can't claim

1. **We cannot attribute a refusal to intent.** The tool reports what was refused, not
   whether refusing was right. Most of our 124 hook refusals were the hook doing its job.
2. **A shape is a heuristic.** `cd`/`VAR=`/`sudo` prefixes are dropped, quoted runs and
   filenames become `<arg>`, URLs `<url>`, a heredoc or `-c` body is cut off, and the
   shape stops at 4 tokens. Two calls a reviewer would call different can land on one
   shape, and `--raw` exists so you can check.
3. **The four layers are only as separable as their strings.** They are matched by prefix
   on the refusal text; a future wording change makes a layer go quiet rather than wrong,
   which is the failure mode we most want you to know about.
4. **The transcript is not a complete record.** It holds what reached the model. A call
   blocked before it was ever issued leaves nothing to count.
5. **Counting by grep overcounts by 4.7x.** The sentence "denied by the Claude Code auto
   mode classifier" appears **242 times** in the same files; **52** are refusals. The rest
   are the agent quoting the refusal in its own notes and issue tracker, and the output of
   greps it ran over those notes. The tool only counts a `tool_result` carrying
   `is_error`, which is why one of its tests is a piece of our own prose that must not
   count.
6. **82 of our 233 refusals happened inside subagents**, where a per-session dashboard
   would not have shown them at all.
7. **"Came back clean" is not "the retry worked."** It means a later call of the same
   shape returned without an error. It is not necessarily the same command, nobody
   proved the wait caused it, and a shape refused once and run a thousand times will
   show a wait of seconds that means nothing. Read the column as evidence that
   *refused* and *impossible* are different words — not as a retry policy.

## Options

| Flag | Meaning |
|---|---|
| `--dir D` / `--file F` | where to read (default `~/.claude/projects`, honours `CLAUDE_CONFIG_DIR`) |
| `--settings F` | a settings file to read `permissions.allow` from (repeatable) |
| `--since` / `--until` | trim the window by date |
| `--window N` | collateral window in seconds (default 120) |
| `--raw` | print the refused commands, credential-shaped strings masked |
| `--json` | machine-readable, for a weekly tally |

Anything that looks like a token (`ghp_…`, `sk-…`, `xox…`, a long hex run) is masked
before printing. **Read the output before you paste it anywhere**: your commands are
your own, and only the shapes are safe by construction.

## Tests

```
python -m unittest test_permission_gap   # 75 tests
python mutation_check.py                 # 33 deliberate breakages, all 33 caught
```

The mutation script edits the tool thirty-three ways and fails if the suite misses any of them.
Several of the thirty are mistakes this tool actually made: a `VAR="…/scratchpad"` prefix
reported as the command, a heredoc delimiter absorbed as a script name, and an allow rule
for `cd *` "covering" everything chained after the `cd` — which inflated the headline
number to 76 before it was caught.

**If you run Claude Code unattended: what are your four counts?** Run it, redact what you
need to, and [paste the four numbers in this thread](https://github.com/samuboon/claude-code-harness/discussions/3),
where ours are — including the one that flipped when we widened the window.
One project's log is not a number.

MIT, same as the rest of this repository.
