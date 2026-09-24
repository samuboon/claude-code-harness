# -*- coding: utf-8 -*-
"""Break changelog_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- most of them are a place where reading a changelog is easy to get
wrong (a date guessed instead of held back, a re-release taken for the next release, a
convention taken for an error). The script runs the suite against each mutated copy and
reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "changelog_check.py"
BAK = HERE / "changelog_check.py.mutation-backup"

MUTATIONS = [
    # reading dates
    ("M1  year-first dates read as year-day-month",
     "d, bad = _mkdate(int(m.group(1)), int(m.group(3)), int(m.group(4)))",
     "d, bad = _mkdate(int(m.group(1)), int(m.group(4)), int(m.group(3)))"),
    ("M2  03/04/2024 guessed instead of held back",
     "        else:\n            return None, m.group(0), \"ambiguous\"",
     "        else:\n            order = \"dmy\""),
    ("M3  a date not on the calendar accepted",
     "        return None, \"%04d-%02d-%02d\" % (y, m, d)",
     "        return dt.date(y, 1, 1), None"),
    ("M4  short month names all read as January",
     "    MONTHS[_k[:3]] = _v",
     "    MONTHS[_k[:3]] = 1"),
    ("M5  the file's own day-first dates not used for the ambiguous ones",
     "        elif sep == \".\" or (dmy_hint or {}).get(sep):",
     "        elif sep == \".\":"),
    ("M6  a date before the version not read",
     "        if pd[2] in (\"ok\", \"bad\"):",
     "        if False:"),
    ("M7  'Released on ...' on the next line not read",
     "                if re.match(r\"(?i)^[_*>\\s(]*(released?|release date|date|published|shipped)\\b\", nxt):\n                    d, dtext, st = find_date(nxt, hint)",
     "                if False:\n                    d, dtext, st = find_date(nxt, hint)"),
    ("M8  a line that is only a date not read",
     "                    if nd[1] and not re.sub(",
     "                    if False and not re.sub("),
    # reading headings
    ("M9  code fences read as headings",
     "        if in_fence:\n            continue\n        if s.lstrip().startswith(\"<!--\"):",
     "        if False:\n            continue\n        if s.lstrip().startswith(\"<!--\"):"),
    ("M10 HTML comments read as headings",
     "            if \"-->\" not in s:\n                in_comment = True",
     "            if False:\n                in_comment = True"),
    ("M11 'Upgrading from 1.9 to 2.0' read as a release",
     "    if len(prefix) > 50 or NOT_RELEASE.search(prefix):",
     "    if len(prefix) > 50:"),
    ("M12 a date written like a version taken as the version",
     "        if m2:\n            m = m2",
     "        if False:\n            m = m2"),
    ("M13 'beta3' after a space dropped",
     "        qm = PREWORD.match(rest)",
     "        qm = None"),
    ("M14 'Enterprise' after the version dropped",
     "        edition = em.group(1).lower()",
     "        edition = \"\""),
    ("M15 a sub-heading repeating the version counted",
     "        if parent is not None and parent.ident == e.ident and parent.key == e.key:",
     "        if False:"),
    ("M16 a two-part section heading counted as a release",
     "                                          and not e.date)]",
     "                                          and False)]"),
    ("M17 headings two levels down counted",
     "        entries = [e for e in entries if e.level <= top + 1 and (e.level >= top - 1)]",
     "        entries = list(entries)"),
    # versions
    ("M18 a prerelease equal to its release",
     "        pkey = (0, tuple(parts))",
     "        pkey = (1,)"),
    ("M19 alpha11 sorted before alpha9",
     "        for p in re.findall(r\"\\d+|[A-Za-z]+\", pre):",
     "        for p in [pre]:"),
    ("M20 oldest-first files read as newest-first",
     "        seq = list(g) if down >= up else list(reversed(g))       # newest first",
     "        seq = list(g)       # newest first"),
    ("M21 +security re-releases taken as neighbours",
     "        plain = [e for e in seq if not e.special]",
     "        plain = list(seq)"),
    ("M22 duplicates by version only (editions collide)",
     "            by.setdefault(e.ident, []).append(e)",
     "            by.setdefault(e.v, []).append(e)"),
    ("M23 prereleases ordered against finals",
     "            finals = [e for e in es if e.v[1] == (1,)]      # prereleases interleave in date order",
     "            finals = es"),
    # dates against neighbours
    ("M24 FUTURE with no slack for time zones",
     "            if ahead > 2:",
     "            if ahead > 0:"),
    ("M25 a planned date on the top entry is an error",
     "                if is_top and ahead <= 60 and not strict_future:",
     "                if False:"),
    ("M26 same-day releases reported",
     "                if vcmp(a.v, b.v) > 0 and a.date < b.date and not (",
     "                if vcmp(a.v, b.v) > 0 and a.date <= b.date and not ("),
    ("M27 month-only dates compared by day",
     "                        a.date_status == \"month\" or b.date_status == \"month\") and id(a) not in reported:",
     "                        False) and id(a) not in reported:"),
    ("M28 no upper bound read as 'anything goes'",
     "            if hi is None:\n                continue          # no upper bound",
     "            if hi is None:\n                hi = dt.date(9999, 1, 1)          # no upper bound"),
    ("M29 a backport listed by version is an error",
     "                if above is None or not backport:",
     "                if True:"),
    ("M30 the year-off rule dropped",
     "            for dy in (1, -1):\n                try:\n                    alt = e.date.replace(year=e.date.year + dy)\n                except ValueError:\n                    continue\n                if not (lo <= alt <= hi):",
     "            for dy in ():\n                try:\n                    alt = e.date.replace(year=e.date.year + dy)\n                except ValueError:\n                    continue\n                if not (lo <= alt <= hi):"),
    ("M31 PLACEHOLDER never reported",
     "            if e.placeholder and i > 0 and any(o.date for o in seq[:i]):",
     "            if False:"),
    # links
    ("M32 the compare head not checked",
     "                    if hv is not None and hv != e.v:",
     "                    if False:"),
    ("M33 a base that is not older not checked",
     "                    if vcmp(bv, e.v) >= 0:",
     "                    if False:"),
    ("M34 prereleases counted as skipped releases",
     "                               and o.v[1][0] != 0]",
     "                               ]"),
    ("M35 a release that came out after this one counted as skipped",
     "                            if o.date <= e.date:",
     "                            if True:"),
    ("M36 a tag link not checked",
     "                    if tv is not None and tv != e.v:",
     "                    if False:"),
    ("M37 a TBD entry taken as the newest release",
     "                released = [e for e in plain if not e.placeholder] or plain",
     "                released = plain"),
    ("M38 the Unreleased link not checked",
     "                if bv is not None and vcmp(bv, newest.v) < 0 and bv in {o.v for o in plain}:",
     "                if False:"),
    ("M39 LINKDEF where no version is linked at all",
     "                elif version_labels:",
     "                elif defs:"),
    ("M40 DUPLINK for any label",
     "        if VERSION.search(label):\n            f.append(Finding(path, ln, \"warning\", \"DUPLINK\",",
     "        if True:\n            f.append(Finding(path, ln, \"warning\", \"DUPLINK\","),
    # the command line
    ("M41 --strict ignored",
     "    if errors or (a.strict and warnings):",
     "    if errors:"),
    ("M42 node_modules searched",
     "        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(\".\"))",
     "        dirnames[:] = sorted(dirnames)"),
    ("M43 nothing found passes",
     "    if tot[\"files\"] == 0:",
     "    if False:"),
]


def run_tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_changelog_check"],
                       cwd=str(HERE), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    return r.returncode == 0


def main():
    original = SRC.read_text(encoding="utf-8")
    if not run_tests():
        print("the unmutated suite already fails; fix that first")
        return 2
    shutil.copyfile(SRC, BAK)
    survivors = []
    try:
        for name, old, new in MUTATIONS:
            if original.count(old) != 1:
                print("SKIP-BROKEN  %s  (pattern found %d times)" % (name, original.count(old)))
                survivors.append(name + " [pattern missing]")
                continue
            SRC.write_text(original.replace(old, new), encoding="utf-8")
            caught = not run_tests()
            print("%-7s %s" % ("caught" if caught else "SURVIVED", name))
            if not caught:
                survivors.append(name)
    finally:
        shutil.copyfile(BAK, SRC)
        BAK.unlink()
    print("%d of %d mutations caught" % (len(MUTATIONS) - len(survivors), len(MUTATIONS)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
