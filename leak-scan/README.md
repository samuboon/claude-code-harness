**日本語版: [README.ja.md](README.ja.md)**

# leak-scan — the pre-publish check that reads untracked binaries, because that is where ours was hiding

One day before publishing this repository, three `.pyc` files under `tools/__pycache__/` turned out to contain absolute paths carrying the development machine's Windows username and the project's internal code name. We caught it in the last hour before the push. The reason we nearly missed it is the whole design of this tool:

- **`.pyc` files are untracked by git by default**, with no exclusion rule anywhere. They never appeared in `git status` or in any diff.
- **They are binary.** The text scan we ran before publishing could not see inside them either.
- **So both instruments shared one blind spot,** and each of us assumed the other one covered it.

`leak_scan.py` therefore **walks the directory rather than the git index**, opens every file as bytes, and searches each needle **as UTF-8 and as UTF-16LE** — the encoding a string actually has once it is inside a compiled artifact.

Standard library only. No network access. **37 tests, 16 deliberate mutations, all caught.**

---

## Use it as an action

```yaml
- uses: actions/checkout@v4
- uses: samuboon/claude-code-harness@main
  with:
    path: .
    patterns: .github/my-identifiers.txt   # optional
```

| Input | Default | What it does |
|---|---|---|
| `path` | `.` | Directory or file to scan. |
| `patterns` | *(empty)* | Your own identifiers, one per line — see [`patterns.example.txt`](patterns.example.txt). Empty means credentials only. **If you name a file and it is missing or empty, the run fails** rather than quietly scanning with no identifiers. |
| `allow` | *(empty)* | Exceptions, one `relative/path\|needle` per line. `*\|needle` allows a needle anywhere. |
| `exclude` | `.git` | Comma-separated path prefixes to skip. |
| `fail-on` | `any` | `none` reports without failing the job. |

Output: `hits` (a number). Exit codes: **0** no hits / **1** hits found / **2** the scan did not happen.

## Or as a script

```bash
python3 leak_scan.py .
python3 leak_scan.py . --patterns my-identifiers.txt --format github
```

---

## The three rules that make the difference

**1. A scan that read nothing is not a pass.** Zero files read exits **2**, not 0. The failure this prevents is the quiet one: a mistyped path, a scan of an empty directory, and a green check printed over a tree nobody looked at.

**2. The report masks what it found.**

```
  - tools/__pycache__/build.cpython-313.pyc:1 | home path | C:***********
```

CI logs on a public repository are public. A scanner that echoes the secret into the log has moved the leak, not caught it.

**3. Matching a prefix is not finding a key.** `ghp_` and `-----BEGIN ... PRIVATE KEY-----` appear in documentation, in pattern lists, and in this file. A prefix counts only when the right number of key-body characters follows it; a PEM header counts only when base64 follows it. Measured on a fresh checkout of this repository, 2026-09-15 (58 files):

| Rule set | Hits | Of which real |
|---|---:|---:|
| No shape test on key prefixes | 33 | 0 |
| No shape test on PEM headers | 5 | 0 |
| **As shipped** | **0** | — |

**It needs no allow list to scan itself, and that was the point of the last hour of work.** The earlier version reported eight hits on its own test file; the fix was not an exceptions file but assembling the fixtures from pieces (`"password" + "="`), so that no scanner pointed at this tree reports its own test corpus. An allow list you never need beats an allow list you maintain.

The same problem appears for identifiers. A short name matches inside longer words, so matches are checked for word boundaries — and separately for **katakana** boundaries, because Japanese is written without spaces and an unbounded three-character name produced **38 false positives in a single document**. The boundary test is skipped on the UTF-16LE form, where the surrounding bytes are not a reliable guide.

---

## What this does not do

Written before anyone can be disappointed by it.

- **It has never caught a real key in the wild.** It was built after one incident involving a username and a project name, and the credential rules are what a scanner of this kind is expected to carry, not something an incident taught us. Treat the credential half as unproven.
- **The shape tests read the UTF-8 form.** A key stored two bytes per character inside a binary is found by the search and then dropped by `_key_shaped`. So the UTF-16 coverage that this tool exists for is real for **identifiers** and **not** for keys. Known, unfixed, and the first thing to fix.
- **It is not a replacement for a dedicated secret scanner.** Fourteen key prefixes and ten assignment names is a short list next to GitHub secret scanning, `gitleaks` or `trufflehog`, none of which will read your untracked `.pyc` files. Run both.
- **It does not read history.** It scans what is on disk now. A secret already committed and later deleted is not visible to it.
- **It has no entropy test.** A 40-character random string under a name it does not know goes straight past.
- **Speed is untested at scale.** Every rule is searched over every file, and the largest tree it has run on is this one (58 files, well under a second). It has never been pointed at a repository with a `node_modules/`.

---

## Files

| File | |
|---|---|
| `leak_scan.py` | The tool. One file, no imports beyond `argparse` / `sys` / `pathlib`. |
| `test_leak_scan.py` | 37 tests. `python3 test_leak_scan.py` |
| `mutation_check.py` | Breaks the tool 16 specific ways and checks the suite notices. `python3 mutation_check.py`. A test suite nobody has seen fail is decoration; this is how we saw each of these fail once. The original is restored in a `finally` block. |
| `patterns.example.txt` | Commented template for the identifier list. |
| `example-workflow.yml` | The workflow this repository runs on itself. Copy it to `.github/workflows/`. |

Part of [claude-code-harness](../README.md). MIT.
