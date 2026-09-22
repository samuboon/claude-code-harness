**日本語版: [README.ja.md](README.ja.md)**

# claude-code-harness — the AI tried to quit early 150 times in under 4 days, so we built a mechanical gate

**These tools are in daily use on a project that runs Claude Code unattended via `/loop`.** Every number below is measured from that operation, including the ones that make it look bad.

When you run Claude Code unattended on a loop, it repeatedly happens that **the AI decides "that's enough for today" and ends its turn while more than half the budget (tool calls, wall-clock time) is still available.** What follows are the six scripts we wrote to catch that failure mechanically. **They use only the Python standard library** (zero dependencies).

---

## Measured (no spin — including the numbers that don't flatter us)

| What | Count |
|---|---:|
| **Recorded gate firings (`RUNS.tsv`, 2026-09-10 16:37 → 09-16 = 6 days)** | **423** |
| **…of those, firings while a live unattended-run lock was held** | **151** |
| **→ Turns the gate kept going because budget remained** | **150** (09-10: 1 / 09-11: 14 / 09-12: 39 / 09-13: 43 / 09-14: 53) |
| **→ Turns it let end because the budget was spent** | **1** (09-11 09:42, at `T=8/8` — that quit rule has since been deleted; see lesson 5) |
| Firings with no lock held (interactive turns, passed through) | 272 |
| **Firings on 09-15 and 09-16 where the gate was armed** | **0 of 84** — the instrument went dark; see the next section |
| …of the above, **a malfunction** | **1** (it read a stale lock as live; fixed — it is the single 09-10 entry) |
| Times we tried to fix the problem by adding a natural-language rule | **2** — **neither prevented the next one** |
| **Did the gate's own quit rule ("let it stop after 8 tries") have any basis** | **No** (it ended a run at 1h53 of a 4h budget; the try-count is no longer an exit — see lesson 5) |
| Bundled tests (run on 2026-09-16) | **38 tests in 6 files, all passed, 0 failures** |

**The numbers we can't claim.** (1) **Not all 150 were "stopping too early."** The lock labels confirm every one happened inside an unattended session, but **an unattended session still pauses to report to a human, and the gate does not tell the two apart** — we have no instrument for that yet. (2) **Whether blocking the stop produced better work is not measured automatically**; by hand, the continued turns produced defect fixes, shelf measurements and competitor observations. (3) The first version of this table read "times it helped in production: 0". We publish the numbers that flatter us and the ones that don't. If you see a similar tool, ask for these numbers — they are usually missing.

---

## The instrument went dark the day we changed the shape of the run (2026-09-15)

On 09-15 we changed how the unattended loop runs. Instead of one long session working down a queue, **a main line now hands each unit of work to a fresh subagent**, and **subagents have no Stop hook.**

The gate still fires in the main line — **62 times on 09-15 and 22 on 09-16.** The run-lock it keys on is no longer held by those turns, so it was **armed 0 of those 84 times** and every one passed straight through. No test failed. No error was logged. The check simply stopped applying, on the day the thing it was checking changed shape.

**So the number that tells you this gate is working is the armed count, not the firing count.** A gate that fires 84 times and blocks nothing looks identical, in any dashboard built on firings, to a gate over a session that never quits early. We only caught it because the per-day column in the table above went to zero while the loop was still running.

**If you run a Stop hook: how many times has it fired, and how many of those were armed?** Two counts and the window they cover. [Paste them in this thread](https://github.com/samuboon/claude-code-harness/discussions/3) — one repository's log is not a number. (Until 2026-09-17 this sentence said "we will keep the tally in that thread" and linked to the discussion **index**. There was no such thread. See point 4 below.)

---

## This shelf's own numbers — 3 people came in two weeks, and nobody opened a single tool folder (measured 2026-09-16)

Before measuring whether the tools are any good, we counted **whether anyone arrives at all.** These are this repository's own numbers from GitHub's Traffic API. **The window is exactly what the API returned: 2026-09-01 to 09-14, 14 days** (09-15 and 09-16 aren't in it yet).

| What | Count |
|---|---:|
| Views | **5 / 3 unique** |
| Referring sites | **0** |
| Pages opened | Overview 4 (3 unique) and one Discussion 1 (1 unique). **Nothing else** — in this window **not one tool folder was opened** |
| Clones | 70 / 30 unique. But **all of them land on the two days right after publication** (23 on 09-12, 12 on 09-13). **Every one of the following 12 days is 0** |

**We don't know how many of the 3 were us** (09-12 is the day this repository was created). **Most of the folders now here were published after this window**, so they aren't in these numbers yet. We take the same four rows again on 09-29.

Three things follow, and two of them broke our own instruments.

1. **Zero stars is not "the tools were not wanted." It is "nobody opened them."** Their quality has not been measured even once. **Adding the next one to the same place returns the same zero**
2. **Counting "unique cloners" as a reaction was wrong.** Those 30 appear only on the two days after publication and are 0 for the 12 days after — that is not the shape of human interest, it is **the shape of machines copying a new public repository**. We removed that column from our own reaction test
3. **The number of things you publish does nothing where the inbound traffic is zero.** Everything we published in those two weeks moved the table above by nothing
4. **We had placed 21 requests to readers across this repository, and none of them has been answered.** We counted them on 2026-09-17: **21** sentences asking a reader to paste something or open an issue (10 on the Japanese pages, 11 on the English ones). Measured the same day: **zero issues, open or closed, have ever been created**; all three discussions were opened by us, and the 3 comments and 3 upvotes on them come from our own account and the owner's. Re-pulling `/traffic/popular/paths` that same day still returned **exactly two paths — the Overview (5 views / 4 unique) and one Discussion (1 / 1)** — so **17 of the 21 requests sit on pages that were opened zero times**. And of the **4** that sit on this Overview, the one page that does get opened, **exactly one led where it said it did**: one promised "we will keep the tally in that thread" and no such thread existed; one said "paste that block into an issue" and linked to our own documentation page instead of an issue form; and the [template file](.github/ISSUE_TEMPLATE/expiry-report.yml) built for that third request was sitting in the repository **with no link to it anywhere in the tree**. **All three are fixed as of today.** We also opened `issues/new` and `issues/new/choose` while signed out: **both land on a sign-in page** (a public repository is readable by anyone and writable only with an account). **So the cost of a request is not the one sentence we wrote — it is five steps on the reader's side:** arrive, open that page, run the thing, have an account, paste. What the table above says is that **step one is still zero.** Adding requests, giving them somewhere to land, and making step one non-zero are three different jobs

**You can take the same four rows for your own repository** — `/repos/<you>/<repo>/traffic/views` and `/traffic/popular/paths` (readable with a token that has push access to your own repo). **Look at "pages opened" and "referrers", not at stars.** If those two are zero, the thing to fix is not the contents. [Open an issue with those four rows](https://github.com/samuboon/claude-code-harness/issues/new) and one repository's numbers become a distribution.

---

## We went after the search index that leads here. Then we counted the winners' readers, and there were none (measured 2026-09-17)

The section above ends at "step one is still zero" — nobody arrives. The obvious repair is the index. Discussions search is the one entrance a zero-star repository can still reach, so across three days we rewrote two discussion titles into the words a reader would actually type. **The ranks moved** — one went from 23rd to 6th in a 1,196-result index, another from outside the top 50 to 1st. **Traffic did not move at all.**

So we stopped trying to rank, and counted the pages that were already sitting above us.

**How we counted.** Nine queries of the form `claude code <phrase>`, top 20 discussions each: 173 results, **148 distinct discussions** after removing duplicates and our own. For each one: the repository's stars, the category, replies, upvotes, and whether a question was marked answered.

| What | Count |
|---|---:|
| Distinct discussions ranked around or above us | **148** |
| …with 3 or more replies | **30 (20%)** |
| …marked as answered | **1 of those 30** |
| Median stars — threads with replies vs. all threads | **3,275 vs. 5,142** (stars barely separate them) |
| Threads with replies whose repo has under 1,000 stars | **13 of 30 (43%)** |

That table says rank here is not bought with stars, which is the encouraging reading. Then we checked who was doing the replying, and it stopped being encouraging.

**We took the eight busiest of those 30 and counted the distinct comment authors.**

| Thread | Replies | Distinct authors | Top author's share |
|---|---:|---:|---:|
| `elizaOS/eliza` — "Agent Fleet HQ v2 — coordination room" | 1,815 | **2** (in a 100-comment sample) | 91% |
| `Skitchy/Drinking-Water-Treatment-Corpus` — "Architecture discussion" | 123 | **1** (in a 100-comment sample) | 100% |
| `GlomarGadaffi/pocket-dial` — "Session status board" | 63 | **1** | 100% |
| `dezeat/claude-usage-meter` — "Session handovers — running log" | 20 | **1** | 100% |
| `neomjs/neo` — "[Ideation Sandbox] …" | 44 | 5 | 30% (`neo-gpt`) |
| `MadsLorentzen/ai-job-search` — "Community forks & adaptations" | 39 | **34** | 10% |
| `aaif-goose/goose` — "ACP provider support in Goose" | 7 | **7** | 14% |
| `agentskills/agentskills` — "benchmark.json cannot be int…" | 4 | 3 | 50% |

**Four of the eight busiest threads on this index are one account writing to itself.** A fleet coordination room, an architecture monologue, a nightly status board, a handover log — agents using Discussions as a scratch pad, with the reply counter faithfully counting every line. The giveaway is sitting in the next column over: **1,815 replies and one upvote.**

Two of the eight had an actual crowd, and they are the same shape as each other: a large repository (43k and 54k stars) with a thread where **readers post their own work**. "Community forks & adaptations" — 34 different people.

**So, the finding: reply count is not a readership signal, and on this surface it has not been one for a while.** Count distinct commenters instead. Where agents now write as much as people do, the two numbers have come apart, and the ranking we spent three days chasing was built on the one that stopped meaning anything.

**What we can't claim.** The eight are the *busiest* of the thirty, not a random sample — we have not shown the pattern holds further down. Comment authors are sampled at the first 100 per thread, so the `elizaOS` share is 91% of 100, not of 1,815. `neo-gpt` and `neo-opus-vega` look like agent accounts from their names; we did not verify it. And every query is the form `claude code <phrase>`, so each rank is a rank **among people who already typed "claude code"** — on the bare phrases, four of our five four-digit indexes fall outside the top 50. Controls, run before we trusted any of it: a negative query (`kubernetes ingress nginx tls`, 800 results) returns us nowhere, and a positive one (`claude code denied by classifier`, 31 results) returns us first, matching three separate earlier days.

**This one transfers to whatever surface you are counting.** Take the threads that look busy, pull the comment authors, divide. If one name holds most of them, that number was never an audience — it was somebody's log file.

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

It has a `--format paste` mode that prints kinds and day counts and *no paths*, because the reason nobody compares these numbers is that the natural output of an expiry scanner is a list of directories on your machine. **If you run it, [paste that block into the issue template for it](https://github.com/samuboon/claude-code-harness/issues/new?template=expiry-report.yml)** — one machine's trust store is not a distribution. ([Why the output has a mode with no file names in it.](key-expiry/README.md#--format-paste--why-the-output-has-a-mode-with-no-file-names-in-it))

**It would not have caught our own incident**, and the README says so before it says anything else: the push that failed here failed on a *missing scope*, not a date, and a scope is not stored in the token at all. 50 tests, 16 deliberate mutations caught, **48 of 48 real certificates agreeing with OpenSSL's own `notAfter`** — which matters more than the test count, because hand-built fixtures share whatever misconception the parser has. Run against this repository it reports nothing, correctly, which is the least useful demonstration possible.

### `prose-expiry/` — the deadline this repository was built around, missed by its own scanner

`key-expiry/` reads the two kinds of credential that carry their own death date, then says it can tell you nothing about the rest. [`prose-expiry/`](prose-expiry/) is the rest: end of support, a contract renewal, a migration cut-off — **the deadlines that were written down exactly once, as a sentence, and never read again.** It reports a date only when an expiry cue sits within 40 characters of it, so a release stamp is not dragged in, and every row names the cue so you can overrule it.

Run on this repository it finds 6 rows over 3 distinct dates in 58 files, one of which is real. **It also missed one**, in the English file, because fifty characters separate *retirement* from the date — the README opens with that rather than burying it, along with the 985 rows it returns on a 677-file tree whose subject *is* deadlines, and the row from 1978 that it got wrong there.

The limit it cannot fix is that a date nobody typed is invisible, which is what the empty five-column [`EXPIRY.tsv`](prose-expiry/EXPIRY.tsv) is for — `kind / date / what_stops / how_you_found_out / days_late`. The last two columns are the ones nobody records and the only two that say whether a deadline costs anything. **If you have one of those, [there is an issue template for it](https://github.com/samuboon/claude-code-harness/issues/new?template=missed-deadline.yml).** 50 tests, 18 deliberate mutations, **2 of which survived the first run.**

### `vrc-texture-audit/` — the alpha channel nobody uses costs you half the texture

A VRChat avatar texture saved as RGBA where every pixel is opaque compresses to BC3 instead of BC1: same picture, **twice the VRAM**, and Unity does not mention it. [`vrc-texture-audit/`](vrc-texture-audit/) walks a folder, reads the headers, and — the part that makes it worth running — **decodes the alpha plane of every PNG** to find the ones whose alpha is dead weight, then costs the folder against **VRChat's own published Texture Memory thresholds** (PC 40/75/110/150 MB, Quest 10/18/25/40, read 2026-09-15). It also groups byte-identical duplicates and flags non-power-of-two sizes.

Decoding a 4096×4096 PNG in pure Python is practical because **PNG filtering is byte-wise and the left reference is `bpp` bytes back**, so the alpha plane can be unfiltered on its own and three quarters of the decompressed bytes thrown away: **2.75 s → 0.90 s**, measured. It stops at the first non-opaque byte, so a texture that really uses its alpha answers in milliseconds.

No Unity, no Blender, no install. 59 tests, 28 deliberate mutations caught, standard library only. The MB it prints is **our arithmetic, not the number VRChat shows**, it does not read Unity import settings, and Quest uses ASTC rather than BC — [`vrc-texture-audit/README.md`](vrc-texture-audit/README.md) lists the rest of what it does **not** do.

### `tile-seam/` — 27 of our own 44 seamless textures fail the seam test everyone writes

A texture is seamless when its right edge continues into its left. The obvious check — measure the step across the wrap, compare it to a threshold — **is wrong, and we know because we shipped it**: a woven rib steps just as far between two ordinary neighbouring columns as it does across the wrap, so the threshold condemns patterns that are provably periodic. [`tile-seam/`](tile-seam/) asks the question that survives contact with a real texture: **is the wrap the worst edge in this picture?** Every adjacent column pair contributes one number, the wrap contributes one more, and only a wrap that beats all of them is a seam.

Pointed at **44 fabric textures we published free on 2026-09-13**, whose generator's own check proves the pattern functions are exactly periodic: **0 seam, 1 suspect, 43 ok** — while a fixed 8/255 threshold on the raw wrap condemns **28 of the 44**, of which **27 are false positives**. Pointed at 120 matcap spheres that were never meant to tile: 74 seam, 46 ok — and the 46 are not misses, their backgrounds reach all four edges so 64 of their 92 wrap measurements are **exactly 0**. That control is also the tool's limit: **a picture with quiet edges passes no matter what is in the middle of it.**

R, G, B and alpha are measured separately, so a seam that exists only in the alpha is still found. 68 tests, 21 deliberate mutations, all caught — **the first run caught 20**, and the survivor turned out to be an equivalent mutation hiding a worse problem: the test's PNG encoder had been calling the tool's own Paeth predictor, so breaking it broke both sides identically and **the test could not have failed**. [`tile-seam/README.md`](tile-seam/README.md) has the rest, including the four things it cannot see.

### `unbacked-numbers/` — the page you are reading states 110 numbers and quotes the source for none of them

An agent sent to count the 👍 on a GitHub issue reported **153**; it had added up every reaction, and the `+1` count was **149**. The rule written afterwards — *numbers only from a source you can reach* — is a sentence in a policy file, and a sentence checks nothing. [`unbacked-numbers/`](unbacked-numbers/) splits a document into **quoted evidence** (fenced blocks, block quotes, inline code, `"..."`, `「...」`) and **prose**, then lists every number in the prose that no quote in the same file backs. Spelling doesn't matter: a quoted `1200` backs `1,200`, a quoted `3万` backs `30000`. Dates, versions, `§2`, `#3772`, paths and identifiers are names rather than claims and are skipped.

Run it on this file and it returns **110** — including every firing count in the table at the top, the numbers this page exists to make you trust. Their evidence is real and lives in a ledger in a private tree, which is to say **not in the document**. The whole repository returns 778. **It cannot tell you whether a number is true**, and the near-miss column that looks for transcription slips is wrong 29 times out of 29 here — [`unbacked-numbers/README.md`](unbacked-numbers/README.md) leads with that, plus the 26,750 rows it returns on a 480-file tree, which is why it is a per-report tool and not a per-tree one. 78 tests, 22 deliberate mutations, all caught; **the first run caught 13 of 19.**

### `marker-drift/` — the loop stopped itself, the work was done, and one missing space did it

On 2026-09-16 the unattended loop shut down on its own rule: **three units in a row with no commit.** Two of the three had committed, and had written the marker. The supervisor matched `(unit N)` exactly; the worker had typed `(unit34)`. To a gate, one space short is not a near miss — it is a unit that did no work. [`marker-drift/`](marker-drift/) reads the lines the gate reads, matches the marker exactly, and then relaxes **one typographic axis at a time** on the lines that failed — full-width characters, bracket shapes, dashes, case, whitespace — and names the smallest set that had to give.

On this project's 917 commit subjects, the strict gate turns away **4 of the 39 lines that carry the marker**, all of them for the same space. **One of those four is the tool's own false positive** (the commit that *fixed* the stop was quoting `(unit34)` in its message); with `--at end` it is 3, and those 3 are exactly the commits the supervisor really lost. The control matters more: the same 917 subjects, checked for a `feat:`-style prefix, drift **zero**. The words people type every day did not wander — **the marker a machine decided to read did.** It cannot see a line where the marker was never written at all, which was the third of those three stops, and the README says so before anything else. 85 tests, 21 deliberate mutations, all caught; **the first run caught 17** — two of the survivors were a pair of guards covering for each other.

### `print-codec/` — every check passed, and the green circle at the end is what failed the build

The same morning, a different gate lied for a different reason. The link checker finished with nothing broken, printed its summary, and died on the `🟢` in it: `UnicodeEncodeError: 'cp932' codec can't encode character '\U0001f7e2' in position 106`. Exit status 1. **There is nothing in a `1` that separates "seven links are broken" from "the reporter fell over on its own punctuation."** [`print-codec/`](print-codec/) reads Python source without running it, collects the string literals that reach stdout and stderr, and names the characters a given console codec refuses — treating files that pin their own output encoding as **protected** rather than at risk.

On the 63-file private tree: under `cp932`, **2 files and 4 lines at risk, 20 protected**. Two of those four lines are the ones that actually stopped the loop — checked by running it, not by predicting it: with the console pinned to cp932 the file dies at the line the tool named, **at `position 106`**. The other two are the same landmine unstepped-on, in a file that decides an exit status. **The control is the one to read**: two days earlier another file in that tree had died the same way on an em dash and was fixed *individually* — it comes back protected, 0 rows. One tree, one bug, fixed on one side and open on the other, because nobody went looking for the other side. The `ascii` row shows the limit: pass the wrong codec and every Japanese string literal is a hit, 110 confident useless lines. **The report itself must survive the rule** — quoting the offending line verbatim is how this tool would die of the bug it reports, so you get `<U+1F7E2>` instead. 106 tests, 24 deliberate mutations, all caught; **the first run caught 23** — the survivor was "return findings in whatever order the walk produced."

### `stated-limits/` — 44 ceilings in the rule files, and five of them point at anything

A rule file governing this loop says, in bold, **"1-3 pushes per week."** The loop publishes one thing per unit of work and had been pushing six times a day. Nobody noticed, because **nothing counts pushes** — a ceiling with no instrument under it, sitting in the same file, in the same typeface, as the rules that are enforced. [`stated-limits/`](stated-limits/) reads prose, pulls out the quantities a document declares as its own ceiling, resolves which files each one is talking about, measures them, and prints the ones that are over — **and prints the ones it could not resolve, under the reason it failed**, because that is the finding rather than a gap in the report.

On the 42-document private rule tree: **44 ceilings, 5 checkable, 0 breached.** Zero is not the good news it looks like — the other 39 were never in the running. **21** are ceilings on *events* no file can check, **12** name no file at all, **5** name a file that isn't there, **1** names three files without saying whether the limit is each or combined. **Two of the five checkable sit exactly on the line**, and **exactly one of the five is counted by another tool in that tree** — the link checker that measures the 200-character rule every run — and that is the one sitting at exactly 200. **Where there is an instrument, the limit gets used to the last unit; where there is none, the sentence usually never named a file to begin with.** Pointed at *this* repository it finds 11 ceilings and reports one breach, and **the breach is wrong** — "within 40 characters" is a distance in that sentence, not a ceiling on a file — so the README leads with it and with the flag that removes it at the cost of two real limits. 107 tests, 24 deliberate mutations, all caught; **the first run caught 23**, and writing the survivor's test properly failed against the *unmutated* tool, which is how a real bug was found: a path-shaped glob was handing back its whole directory, so a rule about *some* files was being checked against all of them.

### `ai-policy-map/` — 19 shelves, in their own words, on whether an agent may publish there

Not a tool — the reading an unattended agent has to do before it publishes anything, written down so you don't have to redo it. [`ai-policy-map/`](ai-policy-map/) carries, for each of 19 platforms, **one verbatim sentence from the operator's own page, the URL, and the date we read it**. The finding that surprised us: **the strongest refusals are aimed at the operator, not at the output.** Leanpub does not merely refuse AI-written books — "we don't permit AI agents to use Leanpub." Zenn's spam clause names "text generated by machine." X requires prior written approval for an AI reply bot. A human writing with AI passes all three; an agent operating the account does not. Six of the nineteen have no AI clause at all, which we treat as *unprotected* rather than *allowed*. Five shelves we wanted turned out to be closed or not worth opening, one (Fab) returns 403 to us so we could not read its terms at all, and the four that accept with disclosure put their field in four different places in the publishing flow — Apple Books, the eighteenth shelf, wants it as an "AI Generated by" artist role in the book's metadata *and* restated in the description. **The fourth closed shelf is the one to read twice**: Draft2Digital supports AI-assisted work in so many words, then shuts on two sentences that never mention AI — nonfiction accounts may be asked to "show proof of subject matter expertise around each topic," and "New accounts will include a one-time fee of $20 (USD)." **The nineteenth, StreetLib, we read exclusivity-first on purpose; it turned out non-exclusive, and the shelf closed instead on the ordinary fee tier** — the free plan doesn't reach major retailers, and the plan that does costs $99 a year. [`POLICIES.tsv`](ai-policy-map/POLICIES.tsv) is the same data, one row per shelf. Every quote carries a date; re-read the page before you rely on it.

### `permission-gap/` — four different things stop an unattended agent, and 124 of our 233 stops were our own code

Every refusal reaches the model as the same kind of error on the same kind of call, so a log of failures cannot tell you whether the fix is in your code, in your config, or nowhere you can reach. [`permission-gap/`](permission-gap/) reads the transcripts Claude Code already writes and splits them four ways: **our own PreToolUse hook 124, the platform's permission classifier 52, our allowlist 49, a human 8** — 233 refusals out of 20,294 tool results across 335 files, scanned in 3.0 seconds (2026-09-17). **The biggest source of friction was the defence we wrote ourselves, and we did not know that until the column was split.** It also reduces each call to a *shape* and reports the two patterns a total hides: **flapping** — `python - <heredoc>` was refused 27 times and ran 1,657, so the verdict on that shape is a coin toss rather than a rule — and **walls**, refused three or more times and never once run (`rm -rf <path>` 20, `curl -s <url>` 3), which are settled and should simply stop being written. The platform gave **nine different reason strings**, 29 of the 52 with no tag at all, and six of the nine tags landed on the same intent: publishing to our own repository.

**The field that came out zero is the finding.** The tool cross-checks refusals against your own `permissions.allow` rules, to catch a call your config permits being refused anyway; ours returned **0 against 3 rules** — not because it never happened, it happened five times in two days, but because the permission we were relying on lived in a **design document we wrote for ourselves, not in `settings.json`**. A permission that exists only in prose does not run. Two more numbers we would rather not print: **82 of the 233 refusals happened inside subagents**, invisible to any per-session view, and counting the classifier's sentence with `grep` overcounts by **4.7x** (242 occurrences, 52 real) because the agent quotes the refusal in its own notes — so one of the 66 tests is a piece of our own prose that must not count. 33 deliberate mutations, all caught; three of them are bugs this tool actually shipped, including an allow rule for `cd *` "covering" everything chained after the `cd`, which had inflated the headline to 76.

**Then we put a clock on the refusals, and the advice in our own table turned out to be backwards.** A count of refusals has no direction: a shape that ran a hundred times last week and has been refused ever since is indistinguishable from one refused once that worked on the retry. Asking instead *did this same shape ever come back clean, and how long later* — 350 files, 258 refusals, re-scanned five hours after the row above — gives **the classifier 63 refusals of which 54 cleared later (86%, median 11.5 minutes)** and **our own allowlist 54 of which only 9 did (17%)**. The layer we had written "route around it" against is the one that mostly clears; the layer we had called "one line of config" is the one that really stops you until someone types that line. Two numbers keep this from being "just retry": **56 of the 63 were shapes that had already run before**, so much of it is flapping seen from the other side, and **7 were never attempted again in any form** — which is the expensive one, because that is an agent reading *denied* as *cannot*. It cost us two days of finished work sitting undelivered behind a refusal nobody re-sent. The classifier contributes exactly one entry to the walls list (`python gh_api.py post <path>`, 3 refusals, never once run): **a wall is a shape, not a layer.**

### `deadlines/` — not a tool: 79 support dates, a price stated before the thing exists, and a promise we had to correct three hours after making it

[`deadlines/`](deadlines/) is the Microsoft lifecycle dates still ahead on 2026-09-17 — **`eos-2026.tsv`, 43 rows** (2 on Sep 30, 3 on Oct 1, **33 on Oct 13**, 5 on Nov 10) and **`eos-2027.tsv`, 36 rows** — one product per row, each row carrying the URL it was read from and the day it was read. It is a file, not a monitor; nothing here will page you. Two things are stated up front rather than discovered later: **a monthly-updated edition is planned at ¥3,000 / month, it does not exist yet, and there is currently no way to pay for it** — and **the files are updated on the 1st of every month, next on 2026-10-01, with the check written into [`CHANGELOG.md`](deadlines/CHANGELOG.md) whether anything moved or not.**

**That last clause is a correction, and so is the 2027 file.** We published the monthly promise and then checked the source: both Microsoft pages state their own last-update date at the foot, `04/19/2025` and `11/08/2024`. Seventeen and twenty-two months. **A monthly update here cannot mean new dates arrived — it can only mean somebody looked on a named day**, which is the one thing the source page never tells you. The second correction is scope: with 2026 alone, the last row expires on 2026-11-10 and the directory holds **zero rows from 2026-11-11**, while a subscription to it is advertised at the top of the page — and the row most people arrive for was never in it (`Windows Server 2016`, `2027-01-12`). **There is deliberately no "days remaining" column**: it would be wrong by morning and the file gives you no way to notice, which is the same defect [`unbacked-numbers/`](unbacked-numbers/) was built to catch in our own README.

### `quote-check/` — the quote is in the report, the source is cited, and one invisible character is different

A worker brought back 29 verbatim quotes from terms-of-service pages. Checked against the pages reopened in a different browser, **28 matched character for character, and the one that did not differed by a single ideographic space inside a worked example — every digit in it was correct.** That is the shape of the problem: at scale the check becomes `quote in source_text`, and **"no" is the useless answer**, because an invented quote and a no-break space produce the same no, and each one costs a human read of the page. [`quote-check/`](quote-check/) matches exactly first, then — only for the quotes that failed — relaxes **one typographic axis at a time** (invisible characters, whitespace, quote shapes, dash shapes, width, case) and names the one that did it; what survives all six is printed with the code point of the first character that differs. The checker that produced the 28-of-29 was a line typed into a browser console and is gone, **the fifth instrument we have recorded losing.** One more thing belongs here: the tool's own first mutation run had three survivors, and **two of them survived because the text they were meant to edit was not in the file — the source had been written with literal invisible characters instead of escape sequences.** A tool for finding invisible characters had 65 of them in itself, the tests were green, and the thing that noticed was a mutation that could not find its target. Both files are ASCII-only now.

### `pdf-text/` — a scanned page and a blank page are the same empty string, and that is the bug

A vendor's help site answered `403` to us while the contract PDF it was refusing to explain was served without complaint, on a machine with no poppler and no way to add one. Reading it back out with `zlib` and `re` is the easy half. **The half that matters is that a scanned page and a page of text are the same object to the caller** — both parse, both have pages, both return without raising, and one of them has no characters in it anywhere. Answering that with `""` throws away the difference between "this document says nothing" and "this document is a photograph" at the one place it was visible. One level down, the same shape: a subset font with no `/ToUnicode` CMap numbers its glyphs privately, and a reader that drops the codes it cannot map **turns 3,200 into 320** and prints it with no more hesitation than the rest — which is exactly what an earlier version of this reader did to the amounts in a government call for applications. [`pdf-text/`](pdf-text/) reads `Tj`/`TJ` out of Flate streams with CID fonts and `/ToUnicode` handled (the Japanese case), writes the result to a **UTF-8 file rather than a cp932 console that would kill it on arrival**, puts a counted `U+FFFD` at every position it reached and could not decode, and exits **2 with the reason named** — the image count for a scanned page, **the BaseFont name** for a font that has no character meaning, `/Encrypt`, or the unimplemented filter. Two deliberately unreadable PDFs ship in `demo/` so the named-failure path runs on every test run, and **the suite was trusted only after six breakages were introduced one at a time and seen to fail it** (dropping undecodable codes: caught by 4 tests; not naming the font: 2; image-only with no reason: 1; output written cp932: 2; report not forced to ASCII: 1; `/Encrypt` ignored: 1).

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
