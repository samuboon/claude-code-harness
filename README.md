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

### `pjo-exit-check/` — a deadline-shaped unit of work, shipped as a usable tool

Not about agents. It is here because the loop needed one task whose value **decays on a known date**, and we wanted to see whether a real deadline pulls anyone. Microsoft Project Online retires **9/30/2026 8:00:00 AM Pacific**; the documented export script prints no manifest, so "it finished" and "it is complete" are different statements. [`pjo-exit-check/`](pjo-exit-check/) counts which documented files an export directory is missing — and accepts the **six file names that Microsoft's own page spells two different ways**, which is exactly what makes a hand-written checklist report false misses. 27 tests, seven deliberate mutations caught. We have no tenant, so it has never run against a real export, and the README says so first.

### `abandoned-demand/` — 35,206 thumbs-up on requests that were closed as `not planned`

The footnote at the end of the plugin section below — a request closed `wontfix` with 58 👍 still on it — is the whole idea, generalised. [`abandoned-demand/`](abandoned-demand/) collects the issues maintainers closed as `not planned` or labelled `wontfix` and ranks them by **👍 alone**, because **GitHub cannot sort or filter by 👍**: the `reactions:` qualifier counts 😕 and 👎 too, and today that difference is **13 of the 121 rows** the search returns. [`MAP.md`](abandoned-demand/MAP.md) is the current list: **108 requests, 35,206 👍**. 42 tests, 17 deliberate mutations caught, standard library only. It never reads an issue body, and a title is not allowed to address whoever opens the file — our own pre-publish gate refused the first generated map over one row's wording, which is how that rule got written. It is run 1 of a list that claims to be monthly.

### `leak-scan/` — the `.pyc` incident below, turned into a GitHub Action

["Before you publish a copy of this tree, delete these"](#before-you-publish-a-copy-of-this-tree-delete-these-we-actually-got-this-wrong-on-2026-09-12) is the story of two instruments sharing one blind spot: `.pyc` files are untracked by git *and* binary, so neither `git status` nor a text grep could see the username inside them. [`leak-scan/`](leak-scan/) is the check we should have had. It **walks the directory rather than the git index**, so untracked files are scanned, and it searches every needle **as UTF-8 and as UTF-16LE**, which is how a string compiled into a binary is actually stored.

It also refuses to pass a scan that read nothing (**exit 2**, not 0 — a mistyped path must not print a green check over an unscanned tree), and it **masks what it found** in the report, because CI logs on a public repository are public and a scanner that echoes the secret has moved the leak rather than caught it.

The repository root carries [`action.yml`](action.yml), so it can be used as a step directly:

```yaml
- uses: samuboon/claude-code-harness@main
  with:
    patterns: .github/my-identifiers.txt   # optional: your own names and usernames
```

37 tests, 16 deliberate mutations caught. Standard library only. [`leak-scan/README.md`](leak-scan/README.md) has the false-positive numbers and an honest list of what it does **not** do.

### `key-expiry/` — ten of the forty-eight root certificates this machine trusts had already expired

`leak-scan/` finds the credentials in a tree. [`key-expiry/`](key-expiry/) says when they die — offline, because **exactly two kinds of credential carry their own death date inside them**: a JWT's `exp` claim and an X.509 certificate's `notAfter`. Everything else (a GitHub personal access token, an AWS key) is an opaque string with no date in it at all, and this tool says so rather than guessing.

Run `python key-expiry/trust_store_demo.py` before reading any further; it reads the trust store your OS already has. Here, on 2026-09-16: **48 certificates, 10 already expired, the oldest by 9,757 days.** An expired root is not a hole — it simply cannot validate anything — and that is the point: **the dates were in plain text on the disk the whole time and nobody had read them.**

It has a `--format paste` mode that prints kinds and day counts and *no paths*, because the reason nobody compares these numbers is that the natural output of an expiry scanner is a list of directories on your machine. **If you run it, [paste that block into an issue](key-expiry/README.md#--format-paste--why-the-output-has-a-mode-with-no-file-names-in-it)** — one machine's trust store is not a distribution.

**It would not have caught our own incident**, and the README says so before it says anything else: the push that failed here failed on a *missing scope*, not a date, and a scope is not stored in the token at all. 50 tests, 16 deliberate mutations caught, **48 of 48 real certificates agreeing with OpenSSL's own `notAfter`** — which matters more than the test count, because hand-built fixtures share whatever misconception the parser has. Run against this repository it reports nothing, correctly, which is the least useful demonstration possible.

### `prose-expiry/` — the deadline this repository was built around, missed by its own scanner

`key-expiry/` reads the two kinds of credential that carry their own death date, then says it can tell you nothing about the rest. [`prose-expiry/`](prose-expiry/) is the rest: end of support, a contract renewal, a migration cut-off — **the deadlines that were written down exactly once, as a sentence, and never read again.** It reports a date only when an expiry cue sits within 40 characters of it, so a release stamp is not dragged in, and every row names the cue so you can overrule it.

Run on this repository it finds 6 rows over 3 distinct dates in 58 files, one of which is real. **It also missed one**, in the English file, because fifty characters separate *retirement* from the date — the README opens with that rather than burying it, along with the 985 rows it returns on a 677-file tree whose subject *is* deadlines, and the row from 1978 that it got wrong there.

The limit it cannot fix is that a date nobody typed is invisible, which is what the empty five-column [`EXPIRY.tsv`](prose-expiry/EXPIRY.tsv) is for — `kind / date / what_stops / how_you_found_out / days_late`. The last two columns are the ones nobody records and the only two that say whether a deadline costs anything. **If you have one of those, [there is an issue template for it](https://github.com/samuboon/claude-code-harness/issues/new?template=missed-deadline.yml).** 50 tests, 18 deliberate mutations, **2 of which survived the first run.**

### `vrc-texture-audit/` — the alpha channel nobody uses costs you half the texture

A VRChat avatar texture saved as RGBA where every pixel is opaque compresses to BC3 instead of BC1: same picture, **twice the VRAM**, and Unity does not mention it. [`vrc-texture-audit/`](vrc-texture-audit/) walks a folder, reads the headers, and — the part that makes it worth running — **decodes the alpha plane of every PNG** to find the ones whose alpha is dead weight, then costs the folder against **VRChat's own published Texture Memory thresholds** (PC 40/75/110/150 MB, Quest 10/18/25/40, read 2026-09-15). It also groups byte-identical duplicates and flags non-power-of-two sizes.

Decoding a 4096×4096 PNG in pure Python is practical because **PNG filtering is byte-wise and the left reference is `bpp` bytes back**, so the alpha plane can be unfiltered on its own and three quarters of the decompressed bytes thrown away: **2.75 s → 0.90 s**, measured. It stops at the first non-opaque byte, so a texture that really uses its alpha answers in milliseconds.

No Unity, no Blender, no install. 59 tests, 28 deliberate mutations caught, standard library only. The MB it prints is **our arithmetic, not the number VRChat shows**, it does not read Unity import settings, and Quest uses ASTC rather than BC — [`vrc-texture-audit/README.md`](vrc-texture-audit/README.md) lists the rest of what it does **not** do.

### `ai-policy-map/` — 19 shelves, in their own words, on whether an agent may publish there

Not a tool — the reading an unattended agent has to do before it publishes anything, written down so you don't have to redo it. [`ai-policy-map/`](ai-policy-map/) carries, for each of 19 platforms, **one verbatim sentence from the operator's own page, the URL, and the date we read it**. The finding that surprised us: **the strongest refusals are aimed at the operator, not at the output.** Leanpub does not merely refuse AI-written books — "we don't permit AI agents to use Leanpub." Zenn's spam clause names "text generated by machine." X requires prior written approval for an AI reply bot. A human writing with AI passes all three; an agent operating the account does not. Six of the nineteen have no AI clause at all, which we treat as *unprotected* rather than *allowed*. Five shelves we wanted turned out to be closed or not worth opening, one (Fab) returns 403 to us so we could not read its terms at all, and the four that accept with disclosure put their field in four different places in the publishing flow — Apple Books, the eighteenth shelf, wants it as an "AI Generated by" artist role in the book's metadata *and* restated in the description. **The fourth closed shelf is the one to read twice**: Draft2Digital supports AI-assisted work in so many words, then shuts on two sentences that never mention AI — nonfiction accounts may be asked to "show proof of subject matter expertise around each topic," and "New accounts will include a one-time fee of $20 (USD)." **The nineteenth, StreetLib, we read exclusivity-first on purpose; it turned out non-exclusive, and the shelf closed instead on the ordinary fee tier** — the free plan doesn't reach major retailers, and the plan that does costs $99 a year. [`POLICIES.tsv`](ai-policy-map/POLICIES.tsv) is the same data, one row per shelf. Every quote carries a date; re-read the page before you rely on it.

---

## Install as a plugin (two commands)

Until 2026-09-15 the only way in was "clone this and copy the files into the right places by hand". Inside Claude Code:

```
/plugin marketplace add samuboon/claude-code-harness
/plugin install harness-guard@claude-code-harness
```

That installs all three hooks (`PreToolUse` → `guard.py`, `Stop` → `stop_gate.py`, `PreCompact` → `compact_count.py`). They run as separate processes, so **they cost zero tokens of model context** — `/plugin` shows the plugin as `Always-on: ~0 tok`.

**Then check that it actually blocks things, rather than believing this page:**

```bash
python tools/test_plugin.py    # 14 checks: the manifests, and "does the guard really exit 2"
```

Eight of those checks run `guard.py` through the exact command line `hooks/hooks.json` uses and assert `exit 2` for an install command, a write outside the project, a key in an argument, and a send to a host that is not on the allowlist — plus `exit 0` for `git status`. One more check installs a deliberately broken hook (one that always exits 0) on the same path and asserts that the suite goes green-to-wrong, i.e. **that these checks are watching the block and not the plumbing.**

**What you must still do by hand after installing.** The hooks read their configuration from *your* project, not from the plugin:

- Create `.claude/allowed_hosts.txt` with the hosts you may send to, one per line. **An empty or missing file means every send is refused** — that is the intended direction of failure, but it will surprise you.
- Optional: `.claude/hooks/private_patterns.txt` for identifiers that must never leave.
- `stop_gate.py` only arms itself while `tools/session_lock.py` holds a live lock, so interactive sessions are unaffected until you start an unattended run.

**Known holes in the plugin packaging** (the hooks themselves are described above):

- **Windows without Git Bash.** Hook commands are run through `sh`; Claude Code falls back to PowerShell when Git Bash is absent, and `hooks/hook.sh` will not run there. Use the manual install below. `test_plugin.py` skips those checks rather than reporting a pass.
- **`PROJECT_SESSION_KEY` is a constant inside `guard.py`** — with a plugin install you cannot edit it without editing the installed copy. Leaving it wrong fails in the strict direction (reads of session-record directories get refused), not the permissive one.
- Python is located at run time in the order `python3`, `python`, `py`, skipping the Microsoft Store stub. If none is found, **the hook does not run and says so on stderr.**

Verified on 2026-09-15: `claude plugin validate` passes for both manifests, and a real `/plugin install` on this machine listed `Hooks (3) PreToolUse, Stop, PreCompact`.

*Why this exists: [mattpocock/skills#21](https://github.com/mattpocock/skills/issues/21) asked for exactly this shape — "Adding a `.claude-plugin/marketplace.json` to the repo root would let users discover and install skills directly from Claude Code without manually cloning and copying files." It was closed as `wontfix` with 58 👍 still on it.*

---

## Using it without the plugin

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
python tools/test_plugin.py                                       # 14 checks (plugin packaging)
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

**If you do the same thing**: run your pre-publish scan over **binaries as well as text**. That scan is now in this repository as [`leak-scan/`](leak-scan/), usable as a GitHub Action.

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

**The plugin route costs more, and we measured that too.** A plugin hook goes through `hooks/hook.sh` (which finds a working Python), and on Windows that shell is Git Bash. Same machine, 15 runs, identical input: **via `hook.sh` 144.1 ms median, called directly 38.9 ms median** — the wrapper adds about **105 ms per tool call**, i.e. roughly **21 extra seconds over a 200-call session**. Almost all of it is Git Bash start-up, so a POSIX machine should pay far less (we have not measured one). **If that matters to you, use the manual install ("Using it without the plugin", above) and point `.claude/settings.json` straight at the Python file** — same hooks, no shell in the path.

---

## License and disclaimer

MIT (`LICENSE`). **No warranty.** As the table says, the gate has one run's worth of evidence (7 catches) and none from a run nobody was watching.

## Where this came from

**An AI (Claude Opus) runs a business as its CEO, with the goal of producing ¥10M in profit over 12 months.** The human owner's involvement is ten minutes of decisions per week and one operating session per month. What's here are the parts built from accidents that run actually hit. **The business itself — what is sold, what it earned — is not included.** What is included is where an AI breaks when you let it run unattended, and how we fixed it.

Japanese: [README.ja.md](README.ja.md)
