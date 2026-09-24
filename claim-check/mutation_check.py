# -*- coding: utf-8 -*-
"""Break claim_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- reading a quoted "I'll take this" as a new claim, letting a claim
survive the claimant's own pull request, counting 30 days as 29, trusting a timeline that could
not be read. The script runs the suite against each mutated copy and reports any mutation the
suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "claim_check.py"
BAK = HERE / "claim_check.py.mutation-backup"

MUTATIONS = [
    # reading a comment
    ("M1  quoted lines read as the commenter's own words",
     '    t = "\\n".join(l for l in t.splitlines() if not l.lstrip().startswith(">"))\n',
     "    pass\n"),
    ("M2  code blocks read",
     "    t = FENCE_RE.sub(\" \", t)\n",
     "    pass\n"),
    ("M3  HTML comments read",
     "    t = HTML_COMMENT_RE.sub(\" \", t)\n",
     "    pass\n"),
    ("M3b '/assign @someone' read as the maintainer's own claim",
     "    t = ASSIGN_OTHER_RE.sub(\" \", t)\n",
     "    pass\n"),
    ("M4  typographic apostrophe not normalised",
     "    t = t.replace(\"’\", \"'\").replace(\"‘\", \"'\")\n",
     "    pass\n"),
    ("M5  **bold** left in",
     "    t = re.sub(r\"[*~]+|(?<!\\w)_+|_+(?!\\w)\", \"\", t)",
     "    t = t"),
    ("M6  a negation before the claim ignored",
     "            if NEGATION_RE.search(before) or (turn",
     "            if False or (turn"),
    ("M7  'if not, I'll take it' read as a refusal",
     "            before = CONDITION_RE.sub(\" \", s[max(0, m.start() - 40):m.start()])",
     "            before = s[max(0, m.start() - 40):m.start()]"),
    ("M8  a claim taken back in the same sentence kept",
     "            if NEGATION_RE.search(before) or (turn and (RELEASE_RE.search(after, turn.end()) or\n"
     "                                                        NEGATION_I_RE.search(after[turn.end():]))):",
     "            if NEGATION_RE.search(before):"),
    ("M9  any release word anywhere after the claim taken as a refusal",
     "            turn = TURN_RE.search(after)\n",
     "            turn = re.search(r\"\", after)\n"),
    ("M10 'take this opportunity' read as a claim",
     "(?!\\s+(?:opportunity|chance|moment|occasion|into\\s+account|for\\s+granted|way|offline|further|to\\s+the|with\\s+a\\s+grain|back\\b))",
     ""),
    ("M10b 'highly unlikely I will pick this up' read as a claim",
     "busy|unfortunately|unlikely|doubt)",
     "busy|unfortunately)"),
    ("M11 'Working on this would need' read as a claim",
     "                           r\"(?!\\s+(?:would|will|is|requires?|needs?|might|may|could|should|means|seems|was))\")),",
     "                           r\"\")),"),
    # judging an issue
    ("M12 bot comments read",
     "    return bool(e.get(\"bot\") or not who or who.endswith(\"[bot]\") or RELAY_LOGIN_RE.search(who)",
     "    return bool(not who or RELAY_LOGIN_RE.search(who)"),
    ("M12b accounts that relay other trackers read",
     "    return bool(e.get(\"bot\") or not who or who.endswith(\"[bot]\") or RELAY_LOGIN_RE.search(who)\n"
     "                or RELAYED_RE.search(e.get(\"body\") or \"\"))",
     "    return bool(e.get(\"bot\") or not who or who.endswith(\"[bot]\"))"),
    ("M12c a claim on an issue someone else holds reported",
     "        if ep[\"held_by\"] and ep[\"held_by\"] & assigned and k not in assigned:",
     "        if False:"),
    ("M12d an unanswered question of theirs counted as their silence",
     "        waiting = ep[\"asked\"] and not ep[\"members_after_last\"]",
     "        waiting = False"),
    ("M12e a maintainer's reply after their question not noticed",
     "                        ep[\"members_after_last\"] += 1",
     "                        pass"),
    ("M12f being assigned not taken as the answer to 'can I take this?'",
     "                open_eps[who][\"members_after_last\"] += 1  # being assigned answers \"can I take this?\"",
     "                pass"),
    ("M13 a release comment does not end the claim",
     "                if release_in(e.get(\"body\", \"\")) and not claim_in(e.get(\"body\", \"\")):\n"
     "                    del open_eps[who]",
     "                if False:\n"
     "                    del open_eps[who]"),
    ("M14 the claimant's own pull request does not deliver",
     "            if who in open_eps:\n                del open_eps[who]  # delivered",
     "            if who in open_eps:\n                open_eps[who][\"last\"] = e[\"at\"]"),
    ("M15 someone else's pull request does not end the claim",
     "                    del open_eps[k]  # someone else's pull request",
     "                    pass"),
    ("M16 a pull request in another repository ends the claim",
     "            if e.get(\"same_repo\", True) and who:",
     "            if who:"),
    ("M17 a commit does not reset the clock",
     "        elif t in (\"commit\", \"xref\"):",
     "        elif t in (\"xref\",):"),
    ("M18 a later comment does not reset the clock",
     "                else:\n                    ep[\"last\"] = e[\"at\"]",
     "                else:\n                    pass"),
    ("M19 someone else being assigned does not end the claim",
     "            for k in [k for k in open_eps if k != who]:\n                del open_eps[k]\n            if who in open_eps:",
     "            for k in []:\n                del open_eps[k]\n            if who in open_eps:"),
    ("M20 being unassigned does not end the claim",
     "            if who in open_eps:\n                del open_eps[who]\n",
     "            if who in open_eps:\n                pass\n"),
    ("M21 29 days of silence reported as 30",
     "        if silent < days:",
     "        if silent < days - 1:"),
    ("M22 an answer from a maintainer treated as holding the issue",
     "        if still_assigned and not waiting:",
     "        if (still_assigned or ep[\"members\"]) and not waiting:"),
    ("M23 a member's own claim is not a go-ahead",
     "        is_member = ep[\"assoc\"] in MEMBER",
     "        is_member = False"),
    ("M24 closing pull requests ignored",
     "    for pr in issue.get(\"closed_by\", []):",
     "    for pr in []:"),
    ("M25 closed issues judged",
     "    if state_at(issue, events, as_of) != \"open\":\n        return []",
     "    if False:\n        return []"),
    ("M26 --as-of keeps later events",
     "        events = [e for e in events if parse_time(e[\"at\"]) <= as_of]",
     "        events = events"),
    ("M27 --as-of ignores a reopen",
     "        elif e[\"type\"] == \"reopened\":\n            st = \"open\"",
     "        elif e[\"type\"] == \"reopened\":\n            pass"),
    ("M28 current assignees not used when the events say nothing",
     "        assigned = {a.lower() for a in issue.get(\"assignees\", []) if a}",
     "        assigned = set()"),
    ("M29 someone who asked before the silence began counted as asking since",
     "        n_others = sum(1 for at in ep[\"others\"].values() if at > ep[\"last\"])",
     "        n_others = len(ep[\"others\"])"),
    # confirming with a search
    ("M30 #123 taken for #12",
     "    return re.search(r\"(?<![\\w/])#%d\\b|/issues/%d\\b\" % (number, number), text or \"\") is not None",
     "    return re.search(r\"#%d|/issues/%d\" % (number, number), text or \"\") is not None"),
    ("M31 a failed search taken as 'no pull requests'",
     "        if prs is None:\n            failed = True\n",
     "        if prs is None:\n            failed = False\n"),
    ("M31b a failed issue-number search taken as 'no pull requests'",
     "            if got is None:\n                failed = True\n",
     "            if got is None:\n                got = []\n"),
    ("M31c someone else's pull request that names the issue kept",
     "            mine = [p for p in named if (p.get(\"who\") or f.who).lower() == f.who.lower()]",
     "            mine = [p for p in named if (p.get(\"who\") or f.who).lower() == f.who.lower()]\n"
     "            if not mine:\n                kept.append(f)\n                continue"),
    ("M31d a pull request from before the claim taken as moving on",
     "                named = [p for p in got if (p.get(\"at\") or \"9\")[:10] >= since",
     "                named = [p for p in got if True"),
    ("M31e the issue-number search never run",
     "        findings, dropped = confirm(findings, gh.search_prs, gh.search_mentions, sys.stderr)",
     "        findings, dropped = confirm(findings, gh.search_prs, None, sys.stderr)"),
    ("M32 closing pull requests never fetched",
     "                if d[\"number\"] in refs:\n                    d[\"closed_by\"] = refs[d[\"number\"]]",
     "                if False:\n                    d[\"closed_by\"] = refs[d[\"number\"]]"),
    ("M32b a token that hides every cross-reference not reported",
     "            if log and n_closing and not n_xref:",
     "            if False:"),
    ("M33 an unreadable timeline passes",
     "    if any(f.code == \"UNCHECKED\" for f in findings):\n        return 2",
     "    if False:\n        return 2"),
    ("M34 exit 0 on GONE",
     "    return 1 if any(f.severity == \"error\" for f in findings) else 0",
     "    return 0"),
    ("M35 an unreadable timeline judged as an empty one",
     "            d[\"unreadable\"] = getattr(e, \"code\", None) and \"HTTP %s\" % e.code or str(e)[:80]",
     "            pass"),
]


def run_tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_claim_check"],
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
            print("%-8s %s" % ("caught" if caught else "SURVIVED", name))
            if not caught:
                survivors.append(name)
    finally:
        shutil.copyfile(BAK, SRC)
        BAK.unlink()
    print("%d of %d mutations caught" % (len(MUTATIONS) - len(survivors), len(MUTATIONS)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
