# -*- coding: utf-8 -*-
"""Break permission_gap.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This edits the tool in twenty-four
specific ways - each one a mistake a counter of this kind plausibly makes, several of
them mistakes this tool actually made before the tests caught them - runs the suite
against each, and reports any mutation the suite lets through. Exit code 0 means
every mutation was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "permission_gap.py"
BAK = HERE / "permission_gap.py.mutation-backup"

MUTATIONS = [
    ("M1  the denial is matched anywhere in the text, so the agent quoting it counts",
     "    if s.startswith(_CLASSIFIER_PREFIX):",
     "    if _CLASSIFIER_PREFIX in s:"),
    ("M2  a denial with no reason is filed under a reason it never gave",
     '            reason = "(no reason given)"',
     '            reason = "Blocked by classifier"'),
    ("M3  the tool named in an allowlist denial is assumed to be Bash",
     '        return ("allowlist", "not granted", m.group("tool"), (m.group("cmd") or None))',
     '        return ("allowlist", "not granted", "Bash", (m.group("cmd") or None))'),
    ("M4  a human saying no stops being counted at all",
     "    if s.startswith(_HUMAN_PREFIX):",
     "    if False:"),
    ("M5  a hook's whole message becomes the reason, so every path is its own reason",
     '        reason = msg[0].strip() if msg else "(no message)"',
     '        reason = " ".join(msg) if msg else "(no message)"'),
    ("M6  redaction is switched off and a token reaches the screen",
     '    return _SECRET_RX.sub("<redacted>", text)',
     "    return text"),
    ("M7  a leading VAR=value is treated as the command (the bug that made 'scratchpad' a shape)",
     "        while toks and _ASSIGN_RX.match(toks[0][0]):",
     "        while False:"),
    ("M8  `cd x && real-command` reports cd as the command",
     "        if Path(toks[0][0]).name.lower() in _PREAMBLE:",
     "        if False:"),
    ("M9  a heredoc delimiter stops being recognised, so the script body leaks into the shape",
     '        return "<heredoc>"',
     '        return "<arg>"'),
    ("M10 a redirect no longer ends the shape",
     '    if tok[:1] in (">", "<") or tok[:2] in (">>", "2>"):',
     "    if False:"),
    ("M11 a quoted payload becomes part of the command's identity",
     "    if was_quoted:",
     "    if False:"),
    ("M12 two different URLs stop sharing a shape",
     '        return "<url>"',
     "        return tok"),
    ("M13 a filename counts as a subcommand, so every file is its own shape",
     '_SUBCOMMAND_RX = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")',
     '_SUBCOMMAND_RX = re.compile(r"^[a-z][a-z0-9_.-]{0,15}$")'),
    ("M14 the shape is never capped, so long commands never group",
     "MAX_SHAPE_TOKENS = 4",
     "MAX_SHAPE_TOKENS = 99"),
    ("M15 the script name is dropped, so gh_api.py and gh_push.py share a shape",
     '            out.append("-" if rest[0][0] == "-" else Path(rest[0][0]).name)',
     "            pass"),
    ("M16 a file path is kept whole instead of grouped by extension",
     '            ext = Path(val).suffix.lower() or "(no ext)"',
     "            ext = Path(val).name"),
    ("M17 a fetch is keyed by full URL instead of host",
     '        host = re.sub(r"^\\w+://", "", url).split("/")[0].split("?")[0]',
     "        host = url"),
    ("M18 an allow rule for one tool excuses a call to another",
     "        if rule_tool != tool:",
     "        if False:"),
    ("M19 Bash(cd *) excuses whatever was chained after the cd (inflates the headline)",
     '            if rule_head not in ("", "*"):',
     "            if False:"),
    ("M20 a giant tool result is read whole instead of truncated",
     "        return content[:MAX_TEXT]",
     "        return content"),
    ("M21 --since stops cutting the window",
     "            if since and when and when < since:",
     "            if False:"),
    ("M22 calls that ran are not counted, so nothing can ever be seen to flap",
     "                ran[shape] += 1",
     "                pass"),
    ("M23 flapping no longer requires the shape to have run",
     "        if ran.get(shape):",
     "        if True:"),
    ("M24 your own hook counts as the platform denying what you allowed",
     '        if d["layer"] == "own-hook":',
     "        if False:"),
    ("M25 collateral crosses session boundaries",
     '        if 0 <= gap <= window and cur["shape"] != prev["shape"] and cur["session"] == prev["session"]:',
     '        if 0 <= gap <= window and cur["shape"] != prev["shape"]:'),
    ("M26 the collateral window is ignored",
     '        if 0 <= gap <= window and cur["shape"] != prev["shape"] and cur["session"] == prev["session"]:',
     '        if cur["shape"] != prev["shape"] and cur["session"] == prev["session"]:'),
    ("M27 a wall is declared after two denials instead of three",
     "        if n >= 3 and not ran.get(shape):",
     "        if n >= 2 and not ran.get(shape):"),
    ("M28 a shape that has run is still called a wall",
     "        if n >= 3 and not ran.get(shape):",
     "        if n >= 3:"),
    ("M29 denials inside subagents are reported as zero",
     '            "in_subagents": sum(1 for d in denials if d["sidechain"]),',
     '            "in_subagents": 0,'),
    ("M30 a scan that read nothing reports success",
     '    if collected["results"] == 0:',
     "    if False:"),
    ("M31 recovery ignores the direction of the clock, so a run from before the refusal counts as a retry",
     '        later = [t for t in times if t > when]',
     '        later = [t for t in times if t != when]'),
    ("M32 a call that came back as an error counts as having recovered",
     '                if when is not None and not res["is_error"]:',
     "                if when is not None:"),
    ("M33 the successes are left in file order, so the wait is measured to whichever came first in the file",
     "    for times in ran_at.values():\n        times.sort()",
     "    for times in ran_at.values():\n        pass"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "test_permission_gap"],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def main():
    if not SRC.exists():
        print("permission_gap.py is not here")
        return 2
    original = SRC.read_text(encoding="utf-8")
    shutil.copy2(SRC, BAK)
    survived = []
    try:
        if not run_tests():
            print("the suite fails before any mutation. Fix that first.")
            return 2
        print("baseline: the suite passes on the unmutated tool")
        for name, before, after in MUTATIONS:
            if before not in original:
                print("SKIP %s - the line it edits is gone; update this script" % name)
                survived.append(name + "  (stale)")
                continue
            SRC.write_text(original.replace(before, after, 1), encoding="utf-8")
            caught = not run_tests()
            print(("caught   " if caught else "SURVIVED ") + name)
            if not caught:
                survived.append(name)
    finally:
        SRC.write_text(original, encoding="utf-8")
        BAK.unlink(missing_ok=True)

    print()
    if survived:
        print("%d of %d mutations were not caught:" % (len(survived), len(MUTATIONS)))
        for s in survived:
            print("  " + s)
        return 1
    print("all %d mutations caught" % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
