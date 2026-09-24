# -*- coding: utf-8 -*-
"""Break setup_doc_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- most of them are a place where a document is easy to misread as a
shell would not. The script runs the suite against each mutated copy and reports any mutation
the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "setup_doc_check.py"
BAK = HERE / "setup_doc_check.py.mutation-backup"

MUTATIONS = [
    ("M1  a missing npm script is not reported",
     "    if name in scripts:\n        return",
     "    if True:\n        return"),
    ("M2  recipe lines read as rules",
     "MAKE_RULE = re.compile(r\"^([^\\s#=:\\t][^#=:]*?)\\s*(::?)(?!=)\")",
     "MAKE_RULE = re.compile(r\"^\\s*([^\\s#=:\\t][^#=:]*?)\\s*(::?)(?!=)\")"),
    ("M3  cd not followed",
     "        st.cwd = rel\n        return",
     "        st.cwd = cwd\n        return"),
    ("M4  files made by earlier commands forgotten",
     "    for c in st.created:\n        if rel == c or rel.startswith(c + \"/\"):\n            return",
     "    for c in ():\n        if rel == c or rel.startswith(c + \"/\"):\n            return"),
    ("M5  .gitignore not consulted",
     "    if \"node_modules\" in rel.split(\"/\") or ign.ignored(rel) or st.extracted:",
     "    if \"node_modules\" in rel.split(\"/\") or st.extracted:"),
    ("M6  package.json looked for only in the current folder",
     "        if not d:\n            return None\n        d = posixpath.dirname(d)",
     "        return None"),
    ("M7  yarn's fallback to a binary reported as an error",
     "        findings.append((doc, lineno, \"SCRIPT?\", \"%s %s: no script %r in %s (%s would try",
     "        findings.append((doc, lineno, \"SCRIPT\", \"%s %s: no script %r in %s (%s would try"),
    ("M8  output lines of a console block read as commands",
     "            elif prompted:\n                continue",
     "            elif False:\n                continue"),
    ("M9  every line of an unlabelled block read as a command",
     "            if (lang == \"\" or prompted) and not inline and not had_prompt and toks[0] not in TOOLS \\",
     "            if False and not inline and not had_prompt and toks[0] not in TOOLS \\"),
    ("M10 a newer version in the document reported too",
     "    if k[:n] < rk[:n]:",
     "    if k[:n] != rk[:n]:"),
    ("M11 lines that say a version is NOT supported read as requirements",
     "    if not NEED.search(line) or NOT_NEED.search(line):",
     "    if not NEED.search(line):"),
    ("M12 the last alternative of a || range taken instead of the lowest",
     "            best = k if best is None or k < best else best",
     "            best = k"),
    ("M13 Java 1.8 read as 1",
     "        if nums[0] == 1 and len(nums) > 1:\n            nums = nums[1:]",
     "        if False:\n            nums = nums[1:]"),
    ("M14 included Makefiles not read",
     "                t2, p2, c2 = make_targets(repo, sub, seen)",
     "                t2, p2, c2 = set(), [], True"),
    ("M15 an include that cannot be read still counted as complete",
     "                if \"$\" in f or \"*\" in f:\n                    complete = False",
     "                if \"$\" in f or \"*\" in f:\n                    pass"),
    ("M16 pattern rules ignored",
     "            elif \"%\" in t:\n                patterns.append(t.replace(\"%\", \"*\"))",
     "            elif \"%\" in t:\n                pass"),
    ("M17 git clone not followed (the clone's folder read as a missing path)",
     "            st.clone = name\n            st.cwd = \"\\x00out\"",
     "            st.clone = name"),
    ("M18 heredoc bodies read as commands",
     "        if heredoc is not None:\n            if s.strip() == heredoc:",
     "        if False:\n            if s.strip() == heredoc:"),
    ("M19 backslash continuations not joined",
     "            if s.endswith(mark) and not s.endswith(mark * 2):",
     "            if False:"),
    ("M20 warnings fail without --strict",
     "    return 1 if errors or (a.strict and warnings) else 0",
     "    return 1 if errors or warnings else 0"),
    ("M21 no document is a pass",
     "    if stats[\"docs\"] == 0:",
     "    if False:"),
    ("M22 nothing checked goes unsaid",
     "    if stats[\"checked\"] == 0:",
     "    if False:"),
    ("M23 inline code in prose read for paths",
     "                if first in (\"npm\", \"pnpm\", \"yarn\", \"bun\", \"make\"):",
     "                if first in TOOLS:"),
    ("M24 a folder's README read from the root",
     "        st.cwd = st.start = d",
     "        st.start = d"),
    ("M25 npm start without a script, but with server.js, reported",
     "            if repo.exists(norm(posixpath.dirname(pkg_rel), \"server.js\") or \"server.js\"):",
     "            if False:"),
    ("M26 a script in another workspace looked for in the root",
     "            return        # the script lives in another package; not followed",
     "            pass"),
    ("M27 a missing path after a build step is an error",
     "    code = \"PATH?\" if (st.built or st.fetched) else \"PATH\"",
     "    code = \"PATH\""),
    ("M28 the strictest minimum of the repository replaced by the loosest",
     "        return max(mins, key=lambda x: x[0])",
     "        return min(mins, key=lambda x: x[0])"),
    ("M29 a pinned version compared as if it were a minimum",
     "        code = \"VERSION\" if kind == \"min\" else \"VERSION?\"",
     "        code = \"VERSION\""),
    ("M30 a heading does not recover a lost directory",
     "            if st.cwd is None:\n                st.cwd = st.start",
     "            if st.cwd is None:\n                pass"),
    ("M31 pnpm run falls back like yarn (it does not)",
     "        if sub == \"run\":\n            name, kind = next((x for x in rest[1:] if not x.startswith(\"-\")), None), \"run\"\n        elif sub in (\"test\", \"t\", \"start\"):",
     "        if sub == \"run\":\n            name, kind = next((x for x in rest[1:] if not x.startswith(\"-\")), None), \"fallback\"\n        elif sub in (\"test\", \"t\", \"start\"):"),
    ("M32 a Makefile generated by cmake reported missing",
     "            if st.configured or st.fetched or any(c == cwd for c in st.created) or \\",
     "            if False or \\"),
    # added with the fixes after the first scan of 50 public repositories
    ("M33 a command that works read another way still reported",
     "                if not wrong_everywhere:\n                    del findings[n0:]",
     "                if False:\n                    del findings[n0:]"),
    ("M34 output lines of a block that shows prompts read as commands",
     "    if any(PROMPT.match(raw.lstrip()) for _n, raw in block):",
     "    if False:"),
    ("M35 folders named in the prose before a block ignored",
     "                    if rel and repo.isdir(rel):\n                        st.hints.append(rel)",
     "                    if rel and repo.isdir(rel):\n                        pass"),
    ("M36 the .DEFAULT rule not read",
     "            elif t == \".DEFAULT\":",
     "            elif False:"),
    ("M37 inline `make` with no Makefile reported",
     "            if st.inline:\n                return     # prose mentions `make` for other projects too",
     "            if False:\n                return     # prose mentions `make` for other projects too"),
    ("M38 go's own toolchain download not taken into account",
     "        if lang == \"go\" and k >= (1, 21):",
     "        if False:"),
    ("M39 history (\"starting from Node 18\") read as a requirement",
     "previously|starting (?:from|with)|\"",
     "previously|\""),
    ("M40 `cd <repo>/sub` in the repository's own README not followed",
     "            if name and target.startswith(name + \"/\") and not repo.isdir(norm(cwd, target) or \"\\x00\") \\",
     "            if False and not repo.isdir(norm(cwd, target) or \"\\x00\") \\"),
    # added with the fixes after the 25 repositories held out
    ("M41 bash reading the script from stdin read as a file",
     "    if \"-c\" in args or \"-Command\" in args or \"-s\" in args or not pos:",
     "    if \"-c\" in args or \"-Command\" in args or not pos:"),
    ("M42 git worktree add does not make the folder",
     "    if cmd == \"git\" and args[:2] == [\"worktree\", \"add\"]:",
     "    if False:"),
    ("M43 a copy into another repository checked here",
     "        if pos and PLACEHOLDER in pos[-1]:\n            return",
     "        if False:\n            return"),
    ("M44 a tutorial's file, shown in the block before, reported missing",
     "            if st.shown == \"python\" and \"/\" not in a:",
     "            if False:"),
    ("M45 a folder named by a file inside it ignored",
     "                        for p in repo.ending(rel)[:3]:",
     "                        for p in []:"),
    ("M46 a script only a workspace package has reported as an error",
     "    if elsewhere:\n        # `pnpm test`",
     "    if False:\n        # `pnpm test`"),
    ("M47 yarn's colon scripts across workspaces not taken into account",
     "    if cmd == \"yarn\" and \":\" in name and elsewhere:",
     "    if False:"),
    ("M48 inline yarn commands that may be plugins reported",
     "        if st.inline:\n            return         # prose: yarn",
     "        if False:\n            return         # prose: yarn"),
    ("M49 `/docs` in the prose not read as the docs folder",
     "                    rel = norm(\"\", code.strip(\"/\"))",
     "                    rel = norm(\"\", code.rstrip(\"/\"))"),
    # added with the fixes after the second 25 held out
    ("M50 a prompted line whose command is not a known tool skipped",
     "            if (lang == \"\" or prompted) and not inline and not had_prompt and toks[0] not in TOOLS \\",
     "            if (lang == \"\" or prompted) and not inline and toks[0] not in TOOLS \\"),
    ("M51 the folder named in the prose forgotten after one block",
     "            block = []          # the folders the prose named stay until the next heading",
     "            block = []\n            st.hints = []"),
    ("M52 uv init / cargo new do not make the folder",
     "    made = PROJECT_MAKERS.get((cmd, args[0] if args else None))",
     "    made = None"),
    ("M53 any number in rust-toolchain.toml read as the channel",
     "            m = (re.search(r\"^\\s*channel\\s*=\\s*[\\\"'](\\d+\\.\\d+)\", t, re.M) if f.endswith(\".toml\")",
     "            m = (re.search(r\"(\\d+\\.\\d+)\", t) if f.endswith(\".toml\")"),
    ("M54 files unpacked from an archive reported missing",
     "    if \"node_modules\" in rel.split(\"/\") or ign.ignored(rel) or st.extracted:",
     "    if \"node_modules\" in rel.split(\"/\") or ign.ignored(rel):"),
]


def run_tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_setup_doc_check"],
                       cwd=str(HERE), capture_output=True, text=True, env=env)
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
