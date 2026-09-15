**日本語版: [README.ja.md](README.ja.md)**

# pjo-exit-check — count what your Project Online export is missing, before 2026-09-30

Project Online retires on **9/30/2026 8:00:00 AM Pacific Time**. After that the tenant
data is gone. `ExportProjectUserContent.ps1` is the documented way out, and it prints
**no manifest and no summary** — so "the script finished" and "the export is complete"
are two different statements, and you get to find out which one you have exactly once.

This directory is a 450-line script, standard library only, that reads a directory the
export script wrote and tells you which documented files are not in it.

```console
$ python pjo_exit_check.py check C:\pwa1siteOutput
```

It never touches the network, never opens the exported project files, and never writes
to the directory it is checking.

---

## Why a hand-written checklist gets this wrong

The obvious alternative is to open the Microsoft page, write the file names into a
spreadsheet, and tick them off. We tried that first. It produces **false "missing"
results**, because the same documentation page spells the same file two ways in two
places. Every one of these is a real disagreement inside [the export
page](https://learn.microsoft.com/en-us/projectonline/export-user-data-from-project-online),
not a guess of ours:

| in the "Review your exported content" table | in the `-Options` table (Step 4) |
|---|---|
| prefixed with *the project's name* | prefixed with the literal `Project_` |
| `Reporting_ProjectBaseline` | `reporting_Baselines` |
| `BusinessDrivers` | `Drivers.json` (in the prose) |
| `PortfolioAnalysis` | `PortfolioAnalyses` |
| `TaskStatus_AssignmentsHistory` | `TaskStatus_AssignmentHistory` |
| — (not in the table of 27) | `ReportingResourcePlans` |

The script accepts **both spellings of all six** and tells you which one it found. It
also knows that the eight reporting files are called ".json files" in prose but listed
without an extension, so it accepts either, and that `Engagements`, `ResourcePlans`,
`Timesheets` and `TaskStatus_AssignmentsHistory` are paged (`_page1`, `_page2`, …).

And one rule that a checklist cannot express at all: a **feature** file of zero bytes is
documented as normal ("if the user has no data relating to the feature on the specific
PWA site, the file will contain no data"), while a zero-byte **per-project** file is not.
The script reports the first as a note and the second as a failure.

---

## Three commands

```console
$ python pjo_exit_check.py deadline
Project Online retirement : 9/30/2026 8:00:00 AM Pacific Time (= 2026-09-30 15:00 UTC)
  source : https://learn.microsoft.com/en-us/lifecycle/products/project-online
  row    : | Project Online | 3/1/2013 8:00:00 AM | 9/30/2026 8:00:00 AM |

  15 days left (375.0 hours).
  Note the time of day: it is 08:00 Pacific, not midnight local.
```

The lifecycle table states its dates are Pacific, and 2026-09-30 falls inside US daylight
saving time, so the cutoff is **15:00 UTC, not 08:00 UTC**. A countdown that misses that
is seven hours generous on the last day. There is a test whose only job is to fail if
someone deletes that conversion.

```console
$ python pjo_exit_check.py check sample_export --now 2026-09-15
15 days left until 9/30/2026 8:00:00 AM Pacific Time (= 2026-09-30 15:00 UTC)

=== sample_export
  projects    : 2
  expected    : 60 files
  accounted   : 3
  MISSING     : 57
      - Site Rollout : draft .xml
      - Site Rollout : published .xml
      - Site Rollout : draft .mpp
      ... 37 more (use --verbose)

--- 1 director(y/ies): 57 missing, 0 zero-byte
    Re-run ExportProjectUserContent.ps1 for the affected user/PWA site while the
    service still exists.
$ echo $?
1
```

`sample_export/` is three synthetic `*ProjectList.xml` files and nothing else — an export
that named two projects and then wrote none of their files. Expected = 3 project lists +
27 feature files + 15 files per project. Pass several directories at once
(`check out_userA out_userB`) or add `--json`.

```console
$ python pjo_exit_check.py checklist
```

The five things the export script **does not produce**, quoted from the documentation:
custom views/filters/tables/attachments/macros; Project Home favourites (documented
method: take a screenshot); projects the user was not part of; any supported way to load
the `.mpp` files back in; and the master half of an inserted/master pair. A file counter
cannot check these. It can refuse to let you forget them.

Exit codes: `0` nothing missing, `1` something missing or empty, `2` bad usage.

**One run per user per PWA site.** The documentation is explicit that the script exports
only projects the user was a part of. A tenant is users × sites, not one directory —
which is the case `check dirA dirB dirC …` exists for.

---

## What we have not confirmed

We do not have a Project Online tenant. **This script has never been run against a real
export.** Everything it expects is read out of two Microsoft pages, and everything it is
tested against is a directory our own tests create. That is the weakest kind of evidence
there is, and it is the reason for the rest of this list.

- **The internal structure of the exported project `.xml` files is not confirmed, and
  the script does not guess at it.** It does not parse them. It does not open them. The
  only XML it reads is `*ProjectList.xml`, and only for `Proj_Name`, which the
  documentation states is present — and because the element nesting is *also*
  undocumented, it walks the whole tree rather than assuming a path.
- **How the export script turns a project name into a filename is not documented.** If a
  project name contains a character that is not legal in a filename, we do not know what
  the script writes. When it sees such a name the tool says so and marks it NOT
  CONFIRMED rather than reporting a false miss.
- **The extension of the eight reporting files is not confirmed** (prose says `.json`,
  the table omits it). Both are accepted.
- **"Nothing missing" is not "the contents are correct."** This tool counts files. It
  cannot tell you that a `.mpp` opens, that a task list is complete, or that a baseline
  survived.
- **n = 0 users.** No one has used this yet. If it reports a missing file that is
  actually there, that is a bug in our table and we want the filename.

## Who should not use this

If you have a real export in front of you and time to open every file, do that instead —
it is strictly better evidence. This is for the case where you have several hundred files
across several users and fifteen days, and you need to know *which* re-run to spend the
remaining time on.

## Where this came from

We run an unattended agent loop on a hard deadline, and it needed a task whose value
decays on a known date. This was that task. The deadline is real, the documentation
quotes are verbatim, the tool is free, and the honest summary of its evidence is the
section above.

**If you run this against a real export, the result is the thing we most want to see** —
especially a false "missing".
[Open an issue](https://github.com/samuboon/claude-code-harness/issues) with the filename
it got wrong.

---

```console
$ python test_pjo_exit_check.py
Ran 27 tests in 0.465s
OK
```

27 tests. Before adopting them we broke the script in seven specific ways on purpose —
dropping the Pacific conversion, loosening exact matching to prefix matching, counting an
empty feature file as a failure, removing the `reporting_Baselines` alias, removing the
`Project_` prefix, disabling zero-byte detection, and ignoring XML attributes — and
confirmed the suite catches all seven. A test that has never been seen to fail is not
evidence.

Python 3.8+, no dependencies. MIT, same as the rest of this repository.
