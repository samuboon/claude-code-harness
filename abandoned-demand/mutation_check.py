# -*- coding: utf-8 -*-
"""Break abandoned_demand.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite that has never been seen failing is decoration. This script edits a copy of
the tool in fifteen specific ways - each one a mistake we could plausibly make - runs the
suite against each, and reports any mutation that the suite lets through. Exit code 0
means every mutation was caught.

It restores the original file in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "abandoned_demand.py"
BAK = HERE / "abandoned_demand.py.mutation-backup"
BS = "\\"  # keeping backslashes out of the literals below, so the patterns stay readable

MUTATIONS = [
    ("M1  count total_count instead of the thumbs-up",
     'return int((item.get("reactions") or {}).get("+1") or 0)',
     'return int((item.get("reactions") or {}).get("total_count") or 0)'),
    ("M2  ask the server to sort by the mixed total",
     '"sort": "reactions-+1",   # not "reactions": that sorts by the mixed total',
     '"sort": "reactions",'),
    ("M3  stop escaping pipes in table cells",
     'text = str(text).replace("|", "' + BS + BS + '|")',
     'text = str(text)'),
    # M4 was originally "stop replacing \r\n with a space". It survived, because the
    # whitespace fold on the next line already did that job - so the replace was dead code
    # and we deleted it rather than writing a test for it. This is what replaced it.
    ("M4  stop folding whitespace in titles",
     'return " ".join(text.split())',
     'return text'),
    ("M5  dedupe on issue number alone",
     'key = (r["repo"], r["number"])',
     'key = (r["number"],)'),
    ("M6  rank ascending",
     'key=lambda r: (-r["plus_one"], r["repo"], r["number"])',
     'key=lambda r: (r["plus_one"], r["repo"], r["number"])'),
    ("M7  keep the issue body in each row",
     '"reason": item.get("state_reason")',
     '"body": item.get("body"), "reason": item.get("state_reason")'),
    ("M8  stop excluding duplicates",
     'return any(n in EXCLUDE_LABELS for n in label_names(item))',
     'return False'),
    ("M9  never stop paging on a short page",
     'if len(items) < MAX_PER_PAGE:',
     'if False:'),
    ("M10 keep the full timestamp instead of the date",
     '(item.get("closed_at") or "")[:10]',
     '(item.get("closed_at") or "")'),
    ("M11 leave tied rows in an unstable order",
     'key=lambda r: (-r["plus_one"], r["repo"], r["number"])',
     'key=lambda r: -r["plus_one"]'),
    ("M12 stop escaping angle brackets",
     'text = text.replace("<", "&lt;").replace(">", "&gt;")',
     'text = text'),
    ("M13 trust GitHub's reactions: filter instead of re-filtering on thumbs-up",
     'rows = rank([r for r in deduped if r["plus_one"] >= min_reactions])',
     'rows = rank(deduped)'),
    ("M14 report the wrong count of dropped rows",
     '"mixed_total_only": len(deduped) - len(rows),',
     '"mixed_total_only": 0,'),
    ("M15 record the population size on every page instead of once",
     'if page == 1 and totals is not None:',
     'if totals is not None:'),
    ("M16 let a title address the reader again",
     '"title": defang((item.get("title") or "").strip())[0],',
     '"title": (item.get("title") or "").strip(),'),
    ("M17 only cut the word when the title is lower case",
     'low, s = out.lower(), sig.lower()',
     'low, s = out, sig'),
]


def run_tests():
    p = subprocess.run([sys.executable, str(HERE / "test_abandoned_demand.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(HERE))
    err = p.stderr or ""
    return p.returncode, err.count("... FAIL") + err.count("... ERROR")


def main():
    original = SRC.read_text(encoding="utf-8")
    shutil.copy(SRC, BAK)
    survived = []
    try:
        code, failures = run_tests()
        if code != 0:
            print("the unmutated build already fails %d test(s) - fix that first" % failures)
            return 2
        print("baseline: all tests pass\n")
        for name, find, replace in MUTATIONS:
            if find not in original:
                print("SKIPPED  %s  (pattern no longer in the source)" % name)
                survived.append(name)
                continue
            SRC.write_text(original.replace(find, replace, 1), encoding="utf-8")
            code, failures = run_tests()
            if code == 0:
                survived.append(name)
                print("SURVIVED %s  <- the suite did not notice" % name)
            else:
                print("caught   %s  (%d test(s) failed)" % (name, failures))
    finally:
        SRC.write_text(original, encoding="utf-8")
        BAK.unlink(missing_ok=True)
    print("\n%d of %d mutations caught" % (len(MUTATIONS) - len(survived), len(MUTATIONS)))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
