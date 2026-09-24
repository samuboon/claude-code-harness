**日本語: [README.ja.md](README.ja.md)**

# moved-path-check — replicate/cog's AGENTS.md still sends coding agents to a file that was deleted in February

`replicate/cog`'s `AGENTS.md` "provides guidance to coding agents", and its "Important Files"
section lists `python/cog/base_predictor.py` — "Predictor interface". Commit `df576ff` deleted that file on
2026-02-04. `AGENTS.md` was edited again on 2026-04-24 and still lists it, and so does the
project's code-review skill (`.opencode/skills/cog-review/SKILL.md`: "Changes to
`python/cog/base_predictor.py` affect all downstream model authors"). In `GetBindu/Bindu`, the
workflow file written for agents, `.agents/workflows/testing.md`, runs
`uv run pytest tests/unit/test_applications.py` and four other test files by path. All five left
`tests/unit/` on 2026-03-19. Four came back in subfolders within a day
(`test_applications.py` is now `tests/unit/server/test_applications.py`); `test_did_extension.py`
is gone.

Nothing fails when this happens. A path in backticks, or in a shell block, is not a link, so link
checkers do not read it. Grepping the docs for paths that do not exist finds hundreds — example
paths, the reader's own project, build output — so nobody does it. **The repository's history
tells the two apart.** A path that never existed here belongs to somebody else. A path that
existed until a commit removed it is a sentence that went stale.

`moved_path_check.py` reads the docs, looks every path up in `git log`, and reports only the
second kind — with the commit, the date and, when git knows, where the file is now.

```bash
python moved_path_check.py                  # every doc in the checkout you are in
python moved_path_check.py docs/ README.md  # just these
python moved_path_check.py --since v2.0     # only what moved or went away after v2.0
python moved_path_check.py --json
```

On today's default branches (2026-09-24):

```
$ python moved_path_check.py            # in replicate/cog
AGENTS.md:317: error DELETED `python/cog/base_predictor.py` was deleted by df576ff58823 on 2026-02-04
CONTRIBUTING.md:94: error MOVED `pkg/config/cuda_base_images.json` was moved by 2c2259cb1342 on 2026-02-09; it is now `pkg/config/cuda_compatibility.json`
architecture/06-cli.md:261: error DELETED_DIR every file under `pkg/web/` was deleted (the last by 643ad51afeec on 2026-04-30)

$ python moved_path_check.py            # in open-mmlab/mmsegmentation
docs/en/user_guides/useful_tools.md:10: error MOVED `tools/analyze_logs.py` was moved by e0499d5a776d on 2022-08-19; it is now `tools/analysis_tools/analyze_logs.py`
docs/en/user_guides/4_train_test.md:169: error MOVED `configs/pspnet/pspnet_r50-d8_512x1024_40k_cityscapes.py` was moved by a3a144a361fc on 2022-08-26; it is now `configs/pspnet/pspnet_r50-d8_4xb2-40k_cityscapes-512x1024.py`
```

mmsegmentation moved its tools into subfolders and renamed its configs in August 2022. Its
docs still give the old paths four years later — in 8 places in English and 19 in Chinese.

Standard library only. It runs `git` read-only (`ls-files`, `log`, `show`, `check-ignore`) and
writes nothing. Exit code 1 when there is an error, 0 when there is none, **2 when nothing could
be judged** — not a git repository, no docs, or a shallow clone with missing links it cannot look
up. A check that could not read the history must not print a pass.

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `MOVED` | error | The path was renamed; git's history says it is now at the path given. For a relative link the new path is given relative to the doc, ready to paste. |
| `MOVED_DIR` | error | The folder was renamed; at least half of its files went to the new folder named. |
| `DELETED` | error | The path was deleted by the commit named, and git saw no rename. When exactly one file of that name exists now, it is named as a hint. |
| `DELETED_DIR` | error | Every file under the folder was deleted (the last one by the commit named). |
| `HISTORICAL` | warning | One of the above, but the sentence itself says renamed, removed, formerly, deprecated … — it is probably describing the change. |
| `SHORTENED` | warning | The new path ends with the old one (`packages/core/x.ts` → `plugin/packages/core/x.ts`): the doc may be naming it from inside that folder, as people do once they work there. |
| `ELSEWHERE` | warning | Deleted here, but a file whose path ends the same way exists elsewhere. |
| `SPLIT_DIR` | warning | The folder's files went to several places. |

**What it reads.** Relative links and images (`[x](../src/a.py)`, `[id]: path`, `src="…"`), links
to this repository on GitHub on the branch that is checked out (`github.com/OWNER/REPO/blob/main/…`;
a link to another branch, a tag or a commit is left alone — `vuejs/vue`'s `tree/dev/…` links still
work on a branch nobody has touched since 2022), inline code that looks like a path with a slash
(`src/a.py`, `docs/`), the words with a slash in `sh` / `bash` / `console` / `powershell` blocks
(commands only: prompts are required in `console`, and comments are skipped), and rst / AsciiDoc
`include`, `image` and inline literals. A path in backticks is tried from the doc's own folder,
then each folder above it, then the root.

**What it leaves alone, by design.**
- A path that **never existed** in the history. That is somebody else's path: the reader's app, an
  example, another repository. (A relative link to a file that never existed is a typo; link
  checkers already catch those.)
- A path that is **`.gitignore`d today** — it became a local or generated file (`dist/`, a clone of
  another repository kept next to this one). Only the repository's own `.gitignore` files are
  used, not the global excludes of whoever runs the check.
- **Bare names** in backticks (`.env`, `requirements.txt`, `index.js`). In our first measurement
  almost all of them were the reader's files. A bare name in a link is still read.
- `.claude/…`, `.cursor/…` and other dot-folders that do not exist here today: the reader's config.
- **Records.** Changelogs, release notes, upgrade and migration guides, blog posts, RFCs, ADRs,
  versioned docs, work items (`plans/`, `work-items/`, `slices/`, `evidence.md`), any doc with a
  date in its path (`2026-03-14-phase1.md`), `old_files/`, `README_OLD.md`, and docs that say at the
  top that they are superseded. Their job is to name the paths of their day. `--all-docs` reads
  them anyway.
- Code blocks in other languages, output, and trees. Their paths are relative to something the
  checker cannot know.
- Links inside include-fragments (`macros/`, `_includes/`, `partials/`, `snippets/`): they resolve
  from the page that includes them.

**How it knows where a file went.** `git log --raw --no-renames` gives every deletion and addition
without reading a single file, so it works on a `--filter=blob:none` clone. In each commit a
deletion is paired with an addition that has the same blob, else the same file name, else the same
name with another extension (`ask.test.ts` → `ask.test.js`), else the one other file of the same
kind added in the same folder. A deletion left over is then asked of git's own content-based rename
detection (`git show -M40%`) before it is called deleted. Chains are followed (`a` → `b` → `c`), and
for a path that came back and went again, the newest disappearance is the one that counts.

---

## How we know it is right

Everything below was measured on 2026-09-24. The two tests are the ones every tool in this
repository gets: **commits in which people fixed this by hand, replayed before and after**, and
**repositories set aside before any tuning**, on which the first version's precision is reported.
Here the set-aside half was spent on the first version, so the final version was measured on a
third set that nobody had looked at.

**Repositories.** The 200 most-starred repositories above 30,000 stars under 120 MB and the 200
most-starred between 10,000 and 30,000 under 80 MB; 348 of them have a language and 347 could be
cloned. They were halved by a hash of the name before any tuning. For the final version only,
271 more were added — the 300 most-starred between 5,000 and 10,000 stars under 60 MB, less the
ones above and the ones without a language — that no version had been run on. Every Markdown,
MDX, rst and AsciiDoc file was read, and plain-text READMEs.

| | First version, held-out half (181 repos) | Tuning half (166), version 3 | **Final version, 271 repos never looked at** |
|---|---:|---:|---:|
| Errors | 1,318 | 1,352 | **198** (in 42 repositories) |
| Errors judged | 200, drawn at random | 200, drawn at random | **all 198** |
| …real | **38 (19%)** | 152 (76%) | **177 (89%)** |
| …a record of its day (dated plan, work item, sample output) | 105 | 35 | 2 |
| …not this repository's path | 51 | 12 | 18 |
| …the checker's facts were wrong | 6 | 1 | 1 |

*Real* means that a reader of the repository today is told the path is where something is — an
instruction, a command to run here, a reference, a link, a list of files, a translated copy — and
the path is gone. Each error was judged by a separate reviewer — another Claude instance, not the
one that wrote the checker, and without its reasoning — with the clone in hand, reading the doc
around the line and the history of the path; the tool's claim that the path is missing at
`HEAD` held for all 198 in the final set.

**The first version was bad, and the reason is the lesson.** 105 of its 200 sampled errors were in
records. 52 of the 200 came from a single project's dated plans and specs
(`docs/superpowers/plans/2026-03-14-phase1-implementation.md`: "Create:
`packages/core/src/types.ts`" — true the day it was written). 51 were not this
repository's paths at all, and most of those were bare names: `.env`, `requirements.txt`, the
reader's `index.js`. The history said these paths had once existed here, and the history was
right; the docs meant something else. So the checker now skips records and bare names (see
above). Two more fixes came from the tuning half: work items (`work-items/`, `slices/`,
`evidence.md`) are records too, and a `github.com/…/tree/dev/…` link is judged only when `dev` is
the branch being read.

**One bug was found by the numbers, not by a reviewer.** Version 4 dropped 569 of
`alirezarezvani/claude-skills`' errors at once. Its `.gitignore` has Windows line ends, and asking
git whether `engineering/focused-fix/` is ignored makes a line holding only `\r` match every
folder. The checker now asks about a file inside the folder instead, and a test holds that shape.

The 21 final errors that were not real: 7 are paths written from inside a template app of a
monorepo (`zuiidea/antd-admin`'s docs say `src/routes` and mean `apps/basic/src/routes`); 5 are Go's
`database/sql` in `google/go-cloud`, which in 2018 also had a `database/sql/` folder; 3 are the
reader's own `skills/` folder (`GetBindu/Bindu`); 3 are other things that are not this repository's
file (a vendored project's `src/`, changesets' temporary `pre.json`, a file a generator writes into
the reader's app); 2 are one frozen benchmark report; and 1 is a path that is still reachable
through a symbolic link (`higress`'s `.claude/skills` points to `.agents/skills`) — the one case
where the checker's facts were wrong.

Of the final 198, **19 are in files written for coding agents** (`AGENTS.md`, `CLAUDE.md`,
`SKILL.md`, `.agents/workflows/`), in 10 of the 42 repositories. On the other 347 repositories the
final version reports 1,503 errors in 99 of them, 282 of those in agent files; those were not all
judged.

**One change came after the final measurement.** Bindu's test files left `tests/unit/` in one
commit and came back in subfolders in others, so git saw no rename and the measured version said
only "deleted". Now, when exactly one file of that name exists, `DELETED` names it as a hint
("the only file of that name now is `tests/unit/server/test_applications.py`"). It changes no level
and no count above.

**Commits that fixed it by hand.** Commit search for 48 phrasings ("fix path in readme",
"update paths after move", "docs: fix path" …; 23 of the result pages were refused by the rate
limit and not retried) gave 5,397 commits with one parent. In 2,001 of
them a doc lost a word with a slash that the same doc did not add back. 200 of those, drawn at
random from repositories under 40 MB, were replayed: a partial clone, the checker on the changed
docs at the parent and at the commit. **Most were not what this checker is for.** In 141 every
missing path had never existed in the repository (a typo, a downloaded model, a path in another
project), and in 23 the old path still existed at the parent (renamed in the same commit, doc
updated with it); 7 could not be read. That leaves **29 commits that fixed a doc which had gone
stale** — it named a path that an earlier commit had moved or deleted.

| 29 commits that fixed a stale doc | First version | Final version |
|---|---:|---:|
| Every stale path flagged before, none after (**caught**) | 19 | **16** |
| Some of them flagged | 4 | 5 |
| Flagged before, and some lines still flagged after | 2 | 2 |
| None flagged (**missed**) | 4 | 6 |

The replay commits were never used for tuning, so both columns are held out. The replay names the
changed docs on the command line, and a doc named there is read even when it is a record
(`manx`'s `docs/release-2.1.md` below); in a plain run it would be skipped. **The final version
catches fewer than the first**, and that is the price of the precision above. Two commits went
from caught to missed: in `MoamenMahmoud1/erp-api` `scripts/` had moved to `infra/scripts/`, so the
old path is the end of the new one and is now a `SHORTENED` warning; in `brooksbUWO/tweakcc-gilligan`
the commands sat in a code block with no language, which the final version does not read. Misses
in both versions: a path in plain prose with no backticks (`nedap/meta-security`'s
`docs/dm-verity-systemd-x86-64.txt`), a path in backticks inside the text of a link that points
somewhere else, `gateway/{cards,conversation}.rs`, and paths in box-drawn trees. The two "still"
commits fixed some lines and left others — `LegalizeAdulthood/manx` fixed two mentions of
`schema/9-schema.sql` in `docs/release-2.1.md` and left the one on line 9, which the checker still
reports at that commit (the plan was later removed).

`replay_fixes.py` replays the commits in `replay_commits.tsv`. It is the one file here that reads
from the network (`git clone` from github.com).

---

## What it does not do

- **Symbolic links are not followed.** A path through a link that git stores as a symlink (mode
  120000) is reported as missing — the one wrong fact in the final measurement.
- **Paths written from a folder the text names** (`src/` meaning "the app's `src/`") are resolved
  from the doc's folder, its parents and the root only. In a monorepo template this is the largest
  source of false errors left.
- **A Go or Python package name that is also a deleted folder** (`database/sql`) cannot be told
  apart from a path.
- **`pytest path::node` ids** and other paths glued to punctuation it does not know are not read.
  (Bindu's `tests/unit/test_applications.py::TestBinduApplication` on lines 54 and 57 is missed.)
- **A whole command in backticks** (`` `python scripts/install.py --prepare` ``) is not read, only a
  path alone in backticks; nor is a path in prose without backticks.
- **It does not read code blocks with no language, in programming languages, or output.** A stale
  `import` path in a Python example is not found, and neither is `tweakcc-gilligan`'s bare ``` block
  of commands.
- **With `--rev`** it reads a commit without a checkout, and `.gitignore` is not consulted.
- **A shallow clone** hides the history the checker depends on. It says so and exits 2 when a missing
  link cannot be looked up. In GitHub Actions use `fetch-depth: 0`.

**Others that look at this.** Link checkers (`lychee`, `markdown-link-check`) check that a relative
link resolves, not where the file went, and do not read paths in backticks or commands.
[kontext](https://github.com/patkusch/kontext) proves docs stale from git history and tracks moved
folders, for the code paths a doc declares in a `describes:` front-matter field; it does not read
the paths written in the text. We did not find one that reads the paths in the prose and asks git
where they went; tell us if there is one.

## In CI

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # the history is the evidence
- run: python tools/moved_path_check.py
```

`moved_path_check.py` is one file; copy it to wherever the `run:` line points. We have not run this
snippet on GitHub Actions ourselves.

## Tests

`python test_moved_path_check.py` — 60 tests, most of them on a small git repository built in a
temporary folder and removed afterwards. `python mutation_check.py` breaks the checker
43 ways, one at a time, and fails if the tests do not notice: **all 43 are caught; the first run
caught 36 of 42.** Of the six that got through, one was a rename found by identical content, which
git's own rename detection also finds, so no test could tell (the pairing is now tested without
git); four were rules whose tests used an example that another rule already covered (a dated plan
inside `plans/`, a `.txt` file that was prose anyway, an HTML comment that ended the line, an
include-fragment's link that did not reach the moved file); and one was a mistake in the mutation
itself, which changed nothing.

Run on this repository, the checker reports 0 errors and 0 warnings in its 67 docs.
