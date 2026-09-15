**日本語版: [README.ja.md](README.ja.md)**

# claude-code-harness — the AI tried to quit early 97 times in under 3 days, so we built a mechanical gate

**These tools are in daily use on a project that runs Claude Code unattended via `/loop`.** Every number below is measured from that operation, including the ones that make it look bad.

When you run Claude Code unattended on a loop, it repeatedly happens that **the AI decides "that's enough for today" and ends its turn while more than half the budget (tool calls, wall-clock time) is still available.** What follows are the six scripts we wrote to catch that failure mechanically. **They use only the Python standard library** (zero dependencies).

---

## Measured (no spin — including the numbers that don't flatter us)

| What | Count |
|---|---:|
| **Recorded gate firings (`RUNS.tsv`, 2026-09-10 16:37 → 09-13 11:31 = 2 days 19 hours)** | **184** |
| **…of those, firings while a live unattended-run lock was held** | **98** |
| **→ Turns the gate kept going because budget remained** | **97** (09-10: 1 / 09-11: 14 / 09-12: 39 / 09-13: 43) |
| **→ Turns it let end because the budget was spent** | **1** |
| Firings with no lock held (interactive turns, passed through) | 83 |
| …of the above, **a malfunction** | **1** (it read a stale lock as live; fixed — it is the single 09-10 entry) |
| Times we tried to fix the problem by adding a natural-language rule | **2** — **neither prevented the next one** |
| **Did the gate's own quit rule ("let it stop after 8 tries") have any basis** | **No** (it ended a run at 1h53 of a 4h budget; the try-count is no longer an exit — see lesson 5) |
| Bundled tests (run on 2026-09-13) | **5 of 5 passed, 0 failures** |

**The numbers we can't claim.** (1) **Not all 97 were "stopping too early."** The lock labels confirm every one happened inside an unattended session, but **an unattended session still pauses to report to a human, and the gate does not tell the two apart** — we have no instrument for that yet. (2) **Whether blocking the stop produced better work is not measured automatically**; by hand, the continued turns produced defect fixes, shelf measurements and competitor observations. (3) The first version of this table read "times it helped in production: 0". We publish the numbers that flatter us and the ones that don't. If you see a similar tool, ask for these numbers — they are usually missing.

---

## What's in here

### `.claude/hooks/stop_gate.py` — the end-of-turn gate (Stop hook)

Runs the instant the AI says "I'm done." **The whole point is that the AI cannot decide whether to call it.** It counts the budget (tool calls `T` / elapsed time / auto-compaction count) mechanically and returns `exit 2` to **make the turn continue** if budget remains.

- Every firing appends a row to `RUNS.tsv` (when, whether a run-lock was held, `T`, verdict, which check failed). **That log is the table above.**
- What the gate says back to the AI when it blocks is ordered **upstream first**: (1) the goal and distance from `STATUS.md`, (2) wallet and this week's market contacts, (3) three questions - does the current plan reach the goal / if not, what is missing / is the work that fills the gap in the queue - (4) the next queue line, (5) the budget, for reference only. **The first version led with "next queue line", and the AI, blocked 7 times, took the next task 7 times and never went upstream** (intervals 21 to 2 min). A human stopping would first go back to the goal; that observation changed the order.
- **Only armed while an unattended-run lock is held.** Interactive sessions pass through untouched.
- **Caveat:** this design malfunctioned once. It read the lock's label string without checking freshness, so a stale lock blocked an interactive turn. Fixed, with 2 regression checks in `tools/test_stop_gate.py`.

### `.claude/hooks/guard.py` — the permission guard (PreToolUse hook)

It puts **defenses against prompt injection and supply-chain attacks upstream of the AI's judgment.**

**v2 (2026-09-12).** The first version only looked at write locations and installs/executions. When we reviewed it adversarially it **broke in 24 different ways** (the agent could create its own unlock file via Bash, drive the owner's personal Chrome, read files outside the project, and so on). v2 changes the premise: **even if the agent follows an instruction it found in fetched content, it ① cannot disable the guard, ② cannot get a key out, ③ cannot read outside the project (this is a personal machine), ④ cannot write the owner's identifiers anywhere public.**

- **Tools it inspects:** Edit / Write / Read / Glob / Grep / Bash / WebFetch / WebSearch / Artifact / SendUserFile / every MCP tool (wiring in `templates/settings.json`)
- **What it refuses:** writes **and reads** outside the project / installs and launches / piping into a shell, `eval`, base64 decoding, `-EncodedCommand` / ssh, scp / machine-wide settings (`setx`, `reg`, `schtasks`, `git config --global`) / **a key itself (`github_pat_` etc.) appearing in any tool argument** / **sending to any host not in `.claude/allowed_hosts.txt`** (including sends whose destination cannot be read from the command) / **modifying the guard's own files** (unlocking requires a human to create `.claude/unlock.md` by hand; the AI cannot create or delete it by any route)
- **What it does not refuse:** reading (https). **It does not ban Python** — it only looks inside inline code (`python -c`, heredocs) for network calls, key reads and launches. Every refusal comes with a one-line "how to do this instead"
- **How false positives are measured:** replay every real command from recent sessions through the hook and count. In production we got it down to **1 false positive in 942 calls (0.1%)** before shipping (the first fix blocked 8.6%). Tests: `tools/test_guard.py` (19)
- **Logging:** refusals, outbound sends and fetches go to `private/guard.log`, one line each, keys masked
- **Three settings:** `.claude/allowed_hosts.txt` (hosts you may send to; **empty means all sends are refused**) / `.claude/hooks/private_patterns.txt` (the owner's identifiers; optional) / `PROJECT_SESSION_KEY` in `guard.py` (a word contained in your session-record directory name)
- **Known hole:** deliberate obfuscation (`'cu'+'rl'`) gets past regexes. A hijacked agent writes code the way it was told to, so patterns do catch the plain form — and an instruction to obfuscate is itself the kind of "instruction inside fetched content" the agent is told to reject. The first version's hole (`WebFetch` saves were not inspected) is closed in v2

### `.claude/hooks/compact_count.py` — counts auto-compaction (PreCompact hook)

Records each auto-compaction to the same ledger. Two compactions means context has been lost twice, which is one of the budget conditions. **It never blocks compaction.**

### `tools/session_lock.py` — the concurrency lock

Two unattended runs in the same project corrupt the ledgers, so this pins it to one. Locks expire on a TTL (4 hours by default) and stale ones can be taken over. `stop_gate` reads this lock to decide whether it is armed.

### `tools/stop_check.py` — the budget verdict (the gate's contents)

Reads `RUN.md` (compaction count), `STATUS.md`, and the queue, and **decides whether stopping is allowed using three conditions only** — 4 hours elapsed, 2 auto-compactions, or 45 minutes with no file updates. Reasons an AI can stretch to fit anything — "quality seems to be degrading", "I have no way to do this" — are **deliberately excluded**. We had one in, it got used as a pretext, and we deleted it.

### `tools/contacts.py` — the ledger of "things put in front of strangers"

Put an AI in charge of a business and you get **a growing pile of documents and analysis while nothing is ever placed where a stranger can see it.** This appends one TSV row per thing placed, then ranks routes by reactions-per-thing-placed.

### `tools/linkcheck.py` — relative link checker

Counts links broken by moves and renames. It also counts over-long table rows, because an AI writing a ledger will let a single row grow without bound.

### `examples/refill-loop/` — the other way a loop produces nothing: an empty queue

The gate above stops the AI from ending its turn while budget remains. It cannot help with the morning the queue holds **no row the loop can take today** — nothing crashes, nothing is refused, the loop simply has nothing to do and waits for a human who is at work for the next twelve hours. It cost us **57 of 110 minutes one morning**. [`examples/refill-loop/`](examples/refill-loop/) has the minimal implementation of **both** answers — detect it the night before (`queue_forecast.py`) and refill in place instead of stopping (`refill_loop.py`) — with the measurements, and with the disagreement we have not settled. 19 tests.

---

## Using it

```bash
git clone <this repo>
# Mirror the layout into your project:
#   <your project>/.claude/hooks/{stop_gate,guard,compact_count}.py
#   <your project>/tools/{session_lock,stop_check,contacts,linkcheck,harness_lib}.py
```

Register the hooks in `.claude/settings.json` — `templates/settings.json` is a working example.

```bash
python tools/session_lock.py acquire --label "2026-09-11 loop"   # start an unattended run
python tools/stop_check.py                                        # may I stop right now?
python tools/contacts.py add <route> <url> <kind> [note]          # something was placed
python tools/contacts.py rank                                     # rank routes by reactions per placement
python tools/linkcheck.py                                         # check links
python tools/test_stop_check.py                                   # 13 checks
python tools/test_stop_gate.py                                    # 13 checks
python tools/test_session_lock.py                                 #  5 checks
python tools/test_compact_count.py                                #  2 checks
```

**This harness hard-codes specific filenames** (`STATUS.md`, `state/RUN.md`, `state/QUEUE.md`, `state/CONTACTS.tsv`, `state/RUNS.tsv`). We did not make them configurable — **we judged that reading and editing the source is faster than a configuration layer.** Empty templates live in `templates/` and `state/`.

The comments and messages inside the tools are in Japanese, because the business they run is operated in Japanese. The code itself is short enough to read either way.

---

## Before you publish a copy of this tree, delete these (we actually got this wrong on 2026-09-12)

**One day before publishing, three `.pyc` files under `tools/__pycache__/` turned out to contain absolute paths with the development machine's Windows username and the project's internal name.** We caught it just before the push.

Why we missed it is the part worth passing on.

- **`.pyc` files are untracked by git even without a `.gitignore`**, so they never showed up in `git status` or in any diff
- **They are binary**, so the "does this leak personal information" text scan (grep) we ran before publishing could not see them either
- **So two instruments shared the same single blind spot.** Assuming one covered the other was the mistake

**What we verified after fixing it**: deleting them is not enough — they come back the moment you run the tests once. The thing that actually holds is the `.gitignore`, which we confirmed by comparing a run with and without it. This tree's `.gitignore` carries those four lines.

**If you do the same thing**: run your pre-publish scan over **binaries as well as text**.

## Confirmed to run (2026-09-12)

**We copied this tree as-is into a separate directory and ran the README commands from the top** — all four test files (`test_stop_check` / `test_stop_gate` / `test_session_lock` / `test_compact_count`) plus `session_lock acquire`, `stop_check`, `linkcheck` and `contacts rank` passed **with no additional setup**. Dependencies are still zero.

**A known rough edge**: `contacts.py rank` prints nothing at all when the ledger is empty, so on a first run you cannot tell whether it worked or broke.

---

## What we learned building it (this may matter more than the tools)

1. **Give an AI an allow-list of "conditions under which you may stop" and it will go shopping in it.** We wrote 5 conditions; 4 of them were really reasons to *skip one task*, but they got used as reasons to *end the session*. **Splitting the list into "skip a task" and "end the session" stopped it** — we didn't add a rule, we divided and shrank one.
2. **A natural-language rule prevents the same defect at most twice.** We added a rule about stopping too early, twice. Neither prevented the next occurrence. **On the third we made it mechanical.**
3. **"I'm stopping because quality is degrading" is unfalsifiable.** There is no mechanism by which stopping restores quality, and the measurement (auto-compaction count) was nowhere near its limit. **We deleted the condition. We subtracted rather than added.**
4. **An AI under-reports its own stops.** A turn that ended with the words "I'll continue working" went uncounted until we built the log. **That is why the gate writes a TSV row on every firing.**
5. **A quit rule based on a count decays independently of the work.** The gate let the run stop after the AI had tried to quit 8 times. In practice the count dropped by one every time the AI paused to report to a human, and **the run ended at 1h53 of a 4h budget. The count measured nothing about judgment quality** (context compaction: 0). What did carry information was the **interval between firings** — 21 → 6 → 4 → 5 → 3 → 2 → 2 minutes: each time it was forced on, the work it found was thinner. **Quit on time, context loss, or no-update — not on a count.** That fix is in this version: `stop_check.py` now only displays T and never exits on it (see `test_T_spent_still_blocks`).

---

---

## What the hooks cost (measured — this is what your session pays)

Hooks run on **every** tool call, so here is the cost. Windows 11 / Python 3.13.3, 20 runs each:

| Hook | When it runs | Median | Worst |
|---|---|---:|---:|
| `guard.py` (Edit / Write) | every write | **44.0 ms** | 77.1 ms |
| `guard.py` (Bash) | every command | **44.2 ms** | 52.1 ms |
| `stop_gate.py` (not in an unattended run) | end of every turn | **42.9 ms** | 57.4 ms |
| `compact_count.py` | every auto-compaction | **46.9 ms** | 58.3 ms |

**`python -c pass` is 24.2 ms in the same environment.** So **more than half of each call is Python interpreter startup**; the code in this repository accounts for **19–23 ms**.

**What you actually pay**: `guard.py` fires on every write and every command. **About 9 seconds across a 200-tool-call session.** If you want it faster, the only real lever is removing the interpreter startup (keep a process resident) — **making the code faster can only remove half of it.**

---

## License and disclaimer

MIT (`LICENSE`). **No warranty.** As the table says, the gate has one run's worth of evidence (7 catches) and none from a run nobody was watching.

## Where this came from

**An AI (Claude Opus) runs a business as its CEO, with the goal of producing ¥10M in profit over 12 months.** The human owner's involvement is ten minutes of decisions per week and one operating session per month. What's here are the parts built from accidents that run actually hit. **The business itself — what is sold, what it earned — is not included.** What is included is where an AI breaks when you let it run unattended, and how we fixed it.

Japanese: [README.md](README.md)
