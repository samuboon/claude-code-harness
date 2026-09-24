**日本語: [README.ja.md](README.ja.md)**

# migration-collision-check — each branch passes its own checks; the merge adds a second V24

Two people branch from `main`. Each adds the next database migration, and each picks the next
number: `V24__add_is_platform_creator.sql` on one branch, `V24__compete_solve_log_unique_constraint.sql`
on the other. Both branches are green. After the second merge, Flyway will not start. In Django
the same accident is two `0239_*.py` files that both depend on `0238` —
*"Conflicting migrations detected; multiple leaf nodes in the migration graph"* — and in Alembic
it is two revisions with one `down_revision`, and `alembic upgrade head` stops with multiple heads.

The collision does not exist on either branch. It exists only in the merge, so a check that runs
on the branch cannot see it; the first place it shows is the base branch after the merge, or the
deploy.

`migration_check.py` reads the migration files of **Flyway, Django, Alembic, Rails (Active Record)
and golang-migrate** and asks each set the question its own tool asks before it runs anything.
With `--base`, it first builds the tree the merge would give — the base branch, plus what your
branch added since the two split — and reports only what your branch brings in.

```bash
python migration_check.py path/to/repo                      # the tree as it is
python migration_check.py path/to/repo --base origin/main   # what merging HEAD into origin/main gives
python migration_check.py path/to/repo --explain            # also list the sets it found, and files it could not read
```

A branch that adds `V2__mine.sql` while `main` added `V2__theirs.sql` after the split:

```
$ python migration_check.py .
1 migration sets (flyway 1), 2 migration files read; 0 errors, 0 warnings
$ echo $?
0
$ python migration_check.py . --base main
db/migration/V2__mine.sql:1: error DUP Flyway version 2 is also used by db/migration/V2__theirs.sql (Flyway stops: more than one migration with this version)
1 migration sets (flyway 1), 3 migration files read, 1 files added by HEAD since d203f0da5d split from main, 0 finding(s) already on the base not shown; 1 errors, 0 warnings
$ echo $?
1
```

Standard library only. It reads files (and, with `--base`, asks `git` for file lists and
contents); it runs no migration, needs no database, writes nothing and sends nothing
(`replay_fixes.py` below is the one part that reads from GitHub). The last line always says how
many sets and files it read; a repository with no migration set it recognises exits 2 and says
so, instead of passing.

---

## What it reports

| Code | Level | Tool | Meaning |
|---|---|---|---|
| `DUP` | error | Flyway | Two versioned migrations with one version in one location. Versions are read as Flyway reads them: `_` is `.`, each part a number, trailing zero parts dropped — `1_1`, `1.1` and `1.01` are one version, `2.0` is `2`. SQL files and Java/Kotlin classes on one classpath location (`src/main/resources/db/migration` and `src/main/java/db/migration`) are one set. |
| `DUP` | error | golang-migrate | Two up (or two down) files with one version in a folder (`011` and `11` are one version). gobuffalo/pop names (`<v>_<name>.<dialect>[.autocommit].up.sql`) are split by dialect, and a file for one dialect does not collide with the file for all of them. When a `go.mod` requires maragudk/migrate, which orders by the whole file name, a shared number is a warning (`DUP?`). |
| `DUP` / `DUPNAME` | error | Rails | Two migrations with one version, or with one name (`DuplicateMigrationVersionError` / `DuplicateMigrationNameError`). `db/migrate` is read with its subfolders, as Rails globs `**/[0-9]*_*.rb`; `db/<name>_migrate` of a second database is its own set. |
| `CONFLICT` | error | Django | An app with more than one leaf migration. Numbers do not matter (two `0005_*` in a chain are fine); the graph does. Dependencies on the same app are edges, `run_before` is an edge the other way, a squashed migration stands in for every name in its `replaces` (whether those files are still there or not), `__first__` / `__latest__` are ignored. The app label comes from `AppConfig.label` in `apps.py`, else the folder name. A `migrations/` folder without `__init__.py` is not loaded by Django, so it is not read, and a class named `Migration` counts only if its base is a `…Migration`. |
| `HEADS` | error | Alembic | More than one head in one chain (`alembic upgrade head` stops). Chains are joined by `down_revision` only (not `depends_on`), inside one script folder (the nearest folder with `env.py`); a database-named folder under `versions/` (`postgresql/`, `sqlite/`) is its own chain. Separate bases are separate chains. |
| `MISSING` | error | Django, Alembic | A dependency on a migration that is in neither the app nor any `replaces` list (Django: `NodeNotFoundError`); a `down_revision` that is in no revision file. A dependency on an app that is not in the repository (`auth`, a package) is not checked. |
| `DUPREV` | error | Alembic | One revision id in two files. Alembic only warns and keeps one of them. |
| `ORDER` | error | Flyway, golang-migrate | `--base` only. Your branch adds a migration numbered below one the base already has. Flyway refuses it on a database that ran the higher one (`outOfOrder` is false by default; if a config file turns it on, `ORDER` is not checked and the last line says which file). golang-migrate never applies a version below the current one — silently. |
| `DUP?` | warning | Flyway | One version in sibling folders under one `migration` folder (`db/migration/control/V1__…` and `db/migration/tenant/V1__…`). One collision if Flyway's location is the parent (it scans subfolders), none if each folder is its own location — the files do not say which. Folders named after a database (`mysql/`, `postgresql/`, `h2/` …) are taken as one location each and not reported. One line per parent folder. |
| `DUP?` | warning | Rails | A duplicate version inside an engine (a folder with a `.gemspec`): `install:migrations` gives every copy a new version, so only an app that adds the engine's folder to its own paths stops. A duplicate *name* in an engine stays an error — the copy skips the second one. |
| `HEADS?` | warning | Alembic | Several heads where `branch_labels` are used: may be on purpose. |
| `SCHEMA` | warning | Rails | Migrations newer than the version in `db/schema.rb`: the schema dump was not updated after them. |

Folders named `fixtures`, `testdata`, `__fixtures__` or `test_fixtures` are left out (test suites
keep broken migration sets on purpose), and the last line counts what was left out. A file this
Python cannot parse (Python 3.14 allows `except A, B:`, which 3.13 cannot read) is read a second way,
as text, for the same few names; the last line counts those too.

**Exit code:** 0 = no errors (warnings fail only with `--strict`). 1 = errors. 2 = no migration set
found, or `git` failed.

### In CI, on a pull request

```yaml
# .github/workflows/migrations.yml
on: pull_request
jobs:
  migrations:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }          # --base needs the history to find where the branches split
      - run: curl -fsSLO https://raw.githubusercontent.com/samuboon/claude-code-harness/main/migration-collision-check/migration_check.py
      - run: python3 migration_check.py . --base origin/${{ github.base_ref }}
```

This has not been run on GitHub by us; the `--base` path is covered by tests that build a
repository with two branches, not by a live pull request. (The workflow is here and not in
`.github/workflows/` because the key that publishes this folder has no workflow permission.)

---

## Measured

### Commits that fixed a collision, replayed (`replay_fixes.py`)

GitHub's commit search for the words people use when they fix one — "multiple leaf nodes", "merge
migrations", "alembic merge heads", "duplicate Flyway migration version", "rename Flyway migration
conflict", "duplicate migration version rails", "renumber duplicate migration" — gave 106 commits,
all public. For each, the checker ran on the tree just before the commit and on the commit itself,
from the tarballs GitHub serves (held in memory, never unpacked).

**They were split in two before any tuning: 53 to tune on, 53 held out.**

| | Tuning half (53) | Held out (53) — first run, before looking |
|---|---:|---:|
| Flagged before the fix (an error), gone after | 49 | **46** |
| Flagged only as a warning | 1 | 1 |
| Not flagged | 3 | 6 |
| Findings that were not real, on the trees replayed | — | 10, and 2 not checked by hand (one repository keeps staged copies of 10 Alembic revisions outside `versions/`) |

After the fixes the held-out half prompted, all 106 again: **95 flagged before the fix and clean
after** — Django 25 of 26, Alembic 14 of 16, Flyway 30 of 36, Rails 7 of 7, golang-migrate 19 of 21 —
2 more as warnings, 9 not. (That second number is no longer a held-out measurement.) One fix went
the wrong way on the way: reading "a `go.mod` that does not require golang-migrate" as "another
tool" turned 7 real golang-migrate collisions into warnings on this replay, and was taken out.

- **Caught, in the tuning half:** Django forks (`0239_servercargoarrivedlog_delivery_id` and
  `0239_worldobject_tag_notes`, both on `0238`), Alembic's two and three heads, Flyway's two `V24`,
  two `V30`, three pairs at `V100`–`V102`, `V1.0.34` twice, `V42_2` twice; Rails' two
  `20260828000001`; golang-migrate's two `055`, two `000118`, two `085`.
- **Why the 9 were missed.** **6 renamed a file to get out of the way of the other branch** —
  the commit message says so ("to avoid Flyway conflict", "the develop branch already occupied
  0069–0071"), or merging with the base shows it — and the tree before the fix does not contain the
  other branch's file. In the tuning
  half, 3 of 53: the collision was with a file on the other
  branch, which the tree before the fix does not contain (msdnna/tessera: the other branch already
  had `0069`–`0071`; narindra20/projectAsync: an out-of-order rename; nachoechave/comercio-flex). That
  is what `--base` is for; for comercio-flex, merging the branch before the fix into the base
  just before its pull request was merged (`--against pr`) gives the `DUP` at `V020`. For the other
  two the base could not be rebuilt from public data (the pull request found was a later release
  merge, or there was none). 1 more was caught only as a `DUP?` warning (anjanx44/Bazario: `V1` in
  four sibling folders under one `db/migration`, fixed as a real collision). In the held-out half, 3
  more renamed out of the way (thangnq090/evchargingplatform `V202` to `V502`, tenant-hub `V8` to
  `V19`, tobi-techy/RAIL-BACKEND-SERVICE to `300`), and 3 are not explained: SentenciaSQL/animalin
  (one `V3` in the tree before the fix), vortex-tecnologia/rxtrack (the fork the commit merged was not
  in the tree; the merge it added depends on `0039_merge_20260619_1029`, which is not in the
  repository at that commit — a real `MISSING`, checked on GitHub), hussu97/mm-ecommerce (the commit
  re-parents a revision onto `251_noon_commission_incl`, which no revision file at that commit
  declares — flagged as `MISSING`, not checked by hand). One more was a warning only
  (hassan-mohagheghian/job-flow: two heads across `versions/` and `processing/versions/`, where
  `branch_labels` are used).
- **Fixes that left or made another:** Tayebbb/TurfChai's fix renamed `V8` to `V11`, next to an
  existing `V11__ml_pricing_tables.sql`; cscpratapnagar-ai's fix of one version left `V24`, `V25` and
  `V36` doubled and added a second `V23`; formalizese-hub's left two `V49`. The checker flags the
  commit itself (read from the files at that commit).
- **Teams write this check by hand.** The same searches return commits that add one: "add a test
  that fails if two Flyway scripts share the same version" (SentenciaSQL/animalin), "fail in `lint`
  when two migrations claim the same version" (tadasant/zimmer), "flyway-duplicate-version-guard"
  (workin-hr), "migration version collision guard" (evo-crm-community), "CI single-head guard"
  (SaifulHaqueNiloy/supremeai). Each looks at one tree.

```bash
python replay_fixes.py                                   # the 106 commits
python replay_fixes.py owner/name@SHA                    # any other public commit
python replay_fixes.py owner/name@SHA --against pr       # also merge its parent into the base of its pull request
python replay_fixes.py --search "duplicate migration"    # candidates from the commit search (1 API call)
python replay_fixes.py --head owner/name                 # the default branch today
```

### 99 public repositories today

Well-known repositories with migrations — 30 Django, 18 Alembic, 13 Flyway, 25 Rails, 13 golang-migrate
style — on their default branch, 2026-09-24. **Split the same way: 50 to tune on, 49 held out.**
Every finding was then checked by reading the files.

| | Tuning half (50) | Held out (49) — first run, before looking |
|---|---:|---:|
| Repositories with a migration set read | 46 | 43 |
| Errors | 42 in 10 repositories | **34 in 3 repositories** |
| Of those, real | 0 | **0** |

On default branches that run in production every day a real error should be rare, and there was
none: every error was the checker misreading a layout. In the tuning half: squashed migrations
whose replaced files were deleted (kitsune, paperless-ngx, cvat), migrations in Python 3.14 syntax
(`except A, B:`, kitsune and readthedocs), `dependencies = [...] + settings.X` (django-helpdesk),
test fixtures (discourse, golang-migrate), pop's `.autocommit` files (ory/kratos), and duplicate
versions inside Rails engines (spree, decidim). In the held-out half: PostHog's own async-migration
classes in a `migrations/` package, Prefect's separate chains in `versions/postgresql` and
`versions/sqlite`, and Harness's `0001_create_table_a` … `0001_create_table_c`, which its migrator
(maragudk/migrate) orders by the whole name.

After the fixes, all 99: **0 errors**; 741 sets and 34,003 migration files read in 89 repositories
(8 had no set it recognises, 2 were skipped: a tarball over 400 MB and one that did not resolve).
40 warnings in 3 repositories, none a real collision: 13 in spree and 2 in decidim (engines), 25 in
Harness (maragudk/migrate).

---

## Limits

- **File names and the few literal values they carry.** It does not read SQL, does not know which
  migrations a database has applied, and does not run your tool's own validation. `flyway
  validate`, `manage.py makemigrations --check`, `alembic heads` and `rails db:migrate:status` do
  more on one tree; what they cannot do is look at a merge that has not happened.
- **Flyway locations are guessed from the layout.** It does not read `spring.flyway.locations` or
  `Flyway.configure().locations(...)`; that is why sibling folders are a warning. Custom prefixes
  (`sqlMigrationPrefix`) and separators are not read; `V` and `__` are assumed.
- **Django:** the label is read from `apps.py` by a pattern, not by importing it; dependencies are
  the literal `(app, name)` pairs anywhere in the value (so `[...] + settings.X` keeps the literal
  part); `MIGRATION_MODULES` is not read. A squash is assumed to stand in for what it replaces —
  true when none or all of those are applied on your database.
- **Alembic:** revision files are the `.py` files under a `versions/` folder or a folder an
  `alembic.ini` names in `version_locations`; a location set only in `env.py` or `pyproject.toml` is
  not found. A database-named folder under `versions/` is its own chain. Only literal `revision` /
  `down_revision` values are read.
- **golang-migrate:** the same names are used by tools that order by the whole name; only
  maragudk/migrate (in a `go.mod`) is recognised, and then a shared number is a warning.
- **`--base`** reads a file your branch edited from your branch and every other file from the
  base; it does not do a three-way merge of the contents.
- 88 tests. `mutation_check.py` breaks the checker 62 ways and all 62 are caught. **The first run
  of the first 42 caught 41**: two Alembic script folders read as one survived, because no test had
  a fork across the version folders of one environment; that test was added. The other 20 were
  written with the later fixes.
