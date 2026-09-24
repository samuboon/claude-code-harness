**日本語版: [README.ja.md](README.ja.md)**

# setup-doc-check — bat's README says Rust 1.79 builds it; its Cargo.toml refuses anything older than 1.88

A setup section goes stale one rename at a time. The script is now `db:migrate`, the Makefile
lost `convert`, the requirements file moved, the project raised its minimum Python — and the
README still says the old thing, because nothing runs the README.

`setup_doc_check.py` reads the shell commands in a repository's README, CONTRIBUTING and setup
docs and asks **the repository**, not a shell, whether each one can work: is the npm script in
the `package.json` it would reach, is there a Makefile rule for the target, does the file the
command needs exist, is the language version the document names at least the one the project
declares. Nothing is run.

```bash
python setup_doc_check.py path/to/repo
python setup_doc_check.py path/to/repo --doc docs/development.md   # these documents only
python setup_doc_check.py path/to/repo --explain                   # every command read, and where
```

On a copy of `sharkdp/bat` and of `date-fns/date-fns`, 2026-09-24:

```
$ python setup_doc_check.py bat
README.md:430: error VERSION the document says rust 1.79; Cargo.toml rust-version requires 1.88
doc/README-ja.md:369: error VERSION the document says rust 1.79; Cargo.toml rust-version requires 1.88
6 documents, 456 commands read, 5 things checked against the repository, 38 lines not read (substitutions, heredocs), 0 paths skipped as ignored or generated; 2 errors, 0 warnings

$ python setup_doc_check.py date-fns
CONTRIBUTING.md:113: warning PATH? run scripts/build/package.sh: not in the repository (an earlier step may make it); package.sh is at pkgs/core/scripts/build/package.sh
CONTRIBUTING.md:114: warning PATH? cd lib: not in the repository (an earlier step may make it)
CONTRIBUTING.md:131: warning SCRIPT? pnpm run lint: no script 'lint' in the workspace root package.json; 1 workspace package(s) have it, e.g. pkgs/core/package.json
2 documents, 16 commands read, 8 things checked against the repository, 0 lines not read (substitutions, heredocs), 0 paths skipped as ignored or generated; 0 errors, 3 warnings
```

(456 commands read and 5 checked: most of bat's README is `bat` itself being used, which is not
a question the repository can answer.)

Standard library only. Reads files, writes nothing, no network (except `replay_fixes.py`, below).
The last line always says how much was actually checked: a README with no command that touches
the repository says so instead of passing quietly.

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `SCRIPT` | error | `npm run X`, `npm test`, `pnpm run X`: no script `X` in the nearest `package.json` above the folder the command runs in (npm walks up, and so does this). The nearest names are listed. |
| `TARGET` | error | `make X`: no rule for `X` in that Makefile or the files it `include`s (pattern rules and `.DEFAULT` count). |
| `PATH` | error | a file or folder the command needs is not in the repository and no earlier command made it: `cd`, `cp`/`mv` sources, `source`, `./x`, `bash x.sh`, `python x.py`, `node x.js`, `pip install -r x`, `docker compose -f x`, `conda env create -f x`. |
| `NOPROJ` | error | `npm run` with no `package.json` above it, `make` with no Makefile (and nothing that writes one: CMake, configure, meson), `docker compose` with no compose file. |
| `VERSION` | error | the document names an older language version than the repository requires: `engines.node`, `requires-python` / Poetry's `python`, `python_requires`, `go.mod`, Gradle / Maven Java release, `Gemfile` `ruby`, `Cargo.toml` `rust-version`. Prose ("Requires Node 16 or later") and install commands (`nvm install 16`, `pyenv install 3.9`) both count. |
| `SCRIPT?` | warning | `yarn X` / `pnpm X` / `bun run X` with no script `X` (they try a binary of that name next); or a workspace root without the script when a workspace package has it. |
| `TARGET?` | warning | no rule, but the Makefile includes files that could not be read (`include $(TOP)/rules.mk`). |
| `PATH?` | warning | missing, but an earlier step (a build, an install, a download) may have made it. |
| `VERSION?` | warning | below a *pinned* version only (`.nvmrc`, `.python-version`, `.tool-versions`...), or Go 1.21+ below `go.mod` (Go fetches the newer toolchain itself unless `GOTOOLCHAIN=local`). |
| `PINS` | warning | the repository disagrees with itself: `.nvmrc` pins 18, `engines.node` requires 20. |

**How it reads a document.** Fenced blocks labelled `sh`, `bash`, `console`, `powershell` and the
like; in a block that shows prompts (`$ `, `> `, `PS> `), only the prompted lines. An unlabelled
block is read only on lines that start with a known tool. Inline code in prose is read for npm
scripts and make targets only (`Then run \`npm run dev\``), never for paths — prose quotes commands
for too many other reasons. Heredoc bodies, `$(...)` and lines with backquotes are skipped and
counted. `<placeholders>`, `path/to/`, `your-`, `...` and `XXXX` are skipped.

**Which folder a command runs in.** `cd` is followed; `git clone URL [dir]` then `cd dir` is the
repository root; a README inside a folder starts in that folder. What a document does *not* say is
where a new block starts, so a command in a block that did not `cd` is reported only when it is
wrong **every** way it could be read: where the last block left off, where the document starts,
at the root, and in a folder the prose just before it names ("from the `docs` directory",
"the script `scripts/benchmark/compare.sh`"). Things earlier commands make are remembered:
`cp .env.example .env`, `mkdir`, `touch`, `> file`, `python -m venv .venv`, `uv init NAME`,
`cargo new NAME`, `git worktree add DIR`; paths in `.gitignore` and anything after an archive is
unpacked are taken as generated.

**Exit codes:** 0 = no error (warnings do not fail unless `--strict`). 1 = an error.
2 = no document to read.

---

## Measured

### Fixes that projects made to their own READMEs, replayed (`replay_fixes.py`)

We searched GitHub's commit search for commits that say they fixed a README's commands ("fix
README script name", "wrong script name", "make target", "fix setup instructions", in several
organizations including `apache` and `vercel`) and kept the 33 whose diff changes a command a
reader would run. For each one, the checker ran on the repository **before** and **after** the
commit, from the tarballs GitHub serves, with no API calls.

| Commits | Flagged before, gone after | Flagged only after | Not flagged |
|---|---|---|---|
| 27 that fixed the document | **15** commits (27 lines) | 1 | 11 |
| 6 that fixed the repository to match the document | **2** commits (6 lines) | 0 | 4 |

- **Caught, among others:** `redis/node-redis` `7dff63f33d` (CONTRIBUTING's `npm run build:tests-tools`,
  a script `package.json` did not have), `apache/teaclave-trustzone-sdk` `bb1647d333` (the Hello
  World example was not where the docs said, so `cd examples/hello_world-rs` and the `make` after
  it failed), scripts
  renamed under the README (`prisma:migrate` → `db:migrate`, `gen-api-key` → `generate-api-key`,
  `build` → `build:chrome:prod`), Makefile targets that were never there (`make scale`, `make drain`).
- **One went the other way:** `ermesjoandreas/praetrace` `57bf95a63b` renamed `npm run codemap`
  to `codemaps` in the README before `package.json` was renamed; the checker flags the commit's
  *after* side, which was wrong until the next commit.
- **Not flagged, and why.** 8 of the 11 are not a name the repository can answer: a Gradle test
  name (`apache/kafka`), a Go module path (`apache/incubator-seata-go`), a Cargo feature flag
  (`apache/datafusion`), a `chmod` glob (`apache/ranger`), arguments to `grep`, `rm` and `flatc`
  (`apache/arrow-java`), a script's body rather than its name (`vercel/turborepo`), the wrong one
  of two scripts that both exist (`agent-substrate/substrate`), a `readme.txt`. 3 are misses:
  after a `cd` into a folder the repository does not have, the checker loses its place and does
  not read the lines after it (it reports the `cd`); `--workspace` is not followed; and one
  Makefile changed in the same commit.
- The 4 repository fixes not flagged: a missing dependency (not a file), broken recipe bodies, and
  two commits that added the requirements file and the README step together.

```bash
python replay_fixes.py                              # all 33, with every finding before and after
python replay_fixes.py owner/name@SHA               # any other public commit
```

### 100 public repositories on 2026-09-24

The default branch of 100 well-known repositories (Python, JavaScript, Go, Rust), every README,
CONTRIBUTING and setup document at the root, in `docs/` and in `.github/`: 236 documents, 2,813
commands read, 470 checked against the repository.

**We tuned it on 50 of them and held 50 back, in two batches of 25.** On the held-back ones,
before any change they prompted: **errors 9 of 14 real, warnings 2 of 12 real.** The false ones
were a tutorial's `python hello.py` (the file is the block above it), `pnpm test` "in the directory
of the package you changed", `make test` in a README that shows what `make` does, a `/docs` folder
named in a list step, `uv init awesome-project` then `cd awesome-project`, a Rust version read from
an `EUPL-1.2` licence line, `yarn stage` from a plugin, and a few more. Each got a fix and a test;
after that, on all 100: **30 findings, 22 real** (errors 15 of 17, warnings 7 of 13). That second
number is on repositories we had by then looked at, so it is not a held-out measurement.

Real ones, read in the files themselves on 2026-09-24:

| Repository | Document | What it says | What the repository says |
|---|---|---|---|
| sharkdp/bat | README.md:430 (and doc/README-ja.md) | "you need Rust 1.79.0 or higher" | `rust-version = "1.88"` — Cargo refuses older compilers |
| sharkdp/hyperfine | README.md:308 | "Make sure that you use Rust 1.76 or newer" | `rust-version = "1.88.0"` |
| sharkdp/hexyl | README.md:148 | "If you have Rust 1.56 or higher" | `rust-version` 1.88 |
| Textualize/rich | README.md:42 (and README.tr.md, 3.6.3) | "Rich requires Python 3.8 or later" | `python = ">=3.9.0"` |
| moment/luxon | docs/install.md:26, CONTRIBUTING.md | "Supports Node.js 6+"; "Assuming you've installed Node 10"; `npm run docs`; `npm run check-doc-coverage` | `engines.node >=12`; the script is `api-docs`; no `check-doc-coverage` |
| nodejs/undici | CONTRIBUTING.md:197 | `cd docs && npm i && npm run serve` | `docs/` has no `package.json`, so npm uses the root's, whose `serve:website` exits with "Documentation has been moved to '/docs'" |
| tiangolo/typer | docs/contributing.md:40 | `uv pip install -r requirements.txt` (inside the dev container, which mounts the repository as `/code`) | no `requirements.txt` at the root |
| ajv-validator/ajv | CONTRIBUTING.md:168 | `npm run watch` | no `watch` script |
| date-fns/date-fns | CONTRIBUTING.md:113 | `./scripts/build/package.sh` | it is at `pkgs/core/scripts/build/package.sh` |
| golang-migrate/migrate | CONTRIBUTING.md:5 | "e.g. Go 1.11+" | `go 1.25.11` |
| cli/cli | docs/install_source.md:3, .github/CONTRIBUTING.md | "Go 1.26+" | `go 1.27.0` (a warning: Go 1.26 downloads 1.27 by itself unless `GOTOOLCHAIN=local`) |
| drizzle-team/drizzle-orm | CONTRIBUTING.md:58 | `nvm install 18.13.0` | `.nvmrc` is `22` |

**Still false on those 100:** `make bin/gh` (cli/cli's rule is `bin/gh$(EXE):`, a variable),
"`node --test` (Node 20+)" read as a requirement (undici), astro's test files run "in their
directories" named only by a path inside them, pnpm's `pnpm test` in a package directory, and
three examples in `just`'s manual that show what other tools do.

---

## Limits

- **Markdown only.** `readme.txt`, reStructuredText and AsciiDoc are not read.
- **Names, not meanings.** A script that exists but is the wrong one, a Gradle/Cargo/Go task or
  test name, a flag, an environment variable, a port — none of these are checked. Only the
  commands listed above have their path arguments read (`grep x file`, `rm -rf dir` are not).
- `yarn`/`pnpm` workspaces: `--workspace` / `--filter` are not followed; Yarn plugins and
  binaries cannot be known without installing, hence `SCRIPT?`.
- Make: rules generated by `$(eval ...)` or named by variables are not seen (the Makefile is then
  "incomplete" and misses are warnings). `just`, `task` and `mise` recipes are not read.
- The folder guesses (above) trade misses for silence: a block that is wrong from where the last
  block left off but right at the root is not reported.
- 89 tests; `mutation_check.py` breaks the checker 54 ways and all 54 are caught. **The first run
  of the first 32 caught 24**; one of the 8 was an equivalent mutation of a redundant line, which
  we deleted, and the other 7 got tests. The 22 added with later fixes were written after the
  fix; 4 of them first survived because the test's own setup made the line under test
  unreachable (a `cd` into a folder made earlier, an archive unpacked earlier in the same
  document), and 3 had to be rewritten because a later fix changed the line they break.
