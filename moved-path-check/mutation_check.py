# -*- coding: utf-8 -*-
"""Break moved_path_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- pairing a deletion with the wrong addition, forgetting that the
newest disappearance is the one that counts, resolving a link from the wrong folder, taking an
old folder's name for a remark about the past, letting a CRLF .gitignore hide every folder.
The script runs the suite against each mutated copy and reports any mutation the suite lets
through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "moved_path_check.py"
BAK = HERE / "moved_path_check.py.mutation-backup"

MUTATIONS = [
    # history: pairing a deletion with its addition
    ("M1  same blob not paired as a rename",
     "            if cand:\n                pairs[p] = cand[0]\n                used.add(cand[0])\n        for p in dels:",
     "            if False:\n                pairs[p] = cand[0]\n                used.add(cand[0])\n        for p in dels:"),
    ("M2  same file name not paired",
     "            cand = [a for a in by_name.get(posixpath.basename(p), []) if a not in used]",
     "            cand = []"),
    ("M3  a.ts -> a.js not paired",
     "            cand = [a for a in by_stem.get(posixpath.splitext(p)[0], []) if a not in used]",
     "            cand = []"),
    ("M4  one-out-one-in paired across folders",
     "                      and posixpath.dirname(a) == d0]",
     "                      ]"),
    ("M5  git's own rename detection not asked",
     "                alt = self.hist.git_rename(ev.sha, cur)",
     "                alt = None"),
    ("M6  an older disappearance overwrites the newest",
     "            if p in self.gone:\n                continue  # an older",
     "            if False:\n                continue  # an older"),
    ("M7  a chain of renames not followed",
     "            ev2 = self.hist.gone.get(nxt)\n            if ev2 is None:",
     "            ev2 = None\n            if ev2 is None:"),
    ("M8  a folder moved when a minority of its files went together",
     "        if cnt * 2 >= len(under):",
     "        if cnt >= 1:"),
    ("M9  --since ignored",
     "        rng = rev if not since else \"%s..%s\" % (since, rev)",
     "        rng = rev"),
    # the tree
    ("M10 an empty folder left on disk counts as the path",
     "            return os.path.isfile(os.path.join(str(self.root), p))",
     "            return os.path.exists(os.path.join(str(self.root), p))"),
    ("M11 .gitignore not consulted",
     "            if c in ign or c + PROBE in ign:\n                continue",
     "            if False:\n                continue"),
    ("M12 a folder asked about as `dir/` (a CRLF blank line matches it)",
     "            asked += [c, c + PROBE] if code.endswith(\"_DIR\") else [c]",
     "            asked += [c, c + \"/\"] if code.endswith(\"_DIR\") else [c]"),
    ("M13 check-ignore fed newline-separated paths (Windows adds \\r)",
     "                input_text=\"\\0\".join(paths) + \"\\0\", check=False,",
     "                input_text=\"\\n\".join(paths) + \"\\n\", check=False,"),
    # which docs
    ("M14 dated docs read",
     "    if not all_docs and (HISTORY_FILE.match(name) or DATED_RE.search(path) or",
     "    if not all_docs and (HISTORY_FILE.match(name) or"),
    ("M15 changelog and history folders read",
     "        if not all_docs and (dl in HISTORY_DIR or VERSION_DIR.match(d) or OLD_PART.search(d)):",
     "        if not all_docs and (VERSION_DIR.match(d) or OLD_PART.search(d)):"),
    ("M16 old_files/ and README_OLD.md read",
     "        if not all_docs and (dl in HISTORY_DIR or VERSION_DIR.match(d) or OLD_PART.search(d)):",
     "        if not all_docs and (dl in HISTORY_DIR or VERSION_DIR.match(d)):"),
    ("M17 a doc marked superseded read",
     "            if not self.all_docs and SUPERSEDED_RE.search(",
     "            if False and SUPERSEDED_RE.search("),
    ("M18 any .txt read as a doc",
     "        if not (TXT_NAMES.match(name) or in_docs):",
     "        if False:"),
    ("M19 node_modules / vendor read",
     "        if dl in SKIP_DIR:\n            return False",
     "        if False:\n            return False"),
    # reading a doc
    ("M20 relative link resolved from the root",
     "        p = posixpath.normpath(posixpath.join(doc_dir, t))",
     "        p = posixpath.normpath(t)"),
    ("M21 %20 in a link not decoded",
     "    t = urllib.parse.unquote(t)",
     "    t = t"),
    ("M22 #L10 / :12 not stripped",
     "    t = LINE_SUFFIX_RE.sub(\"\", t)",
     "    t = t"),
    ("M23 only the root tried for a path in backticks",
     "        return [posixpath.normpath(posixpath.join(a, body)) for a in ancestors]",
     "        return [posixpath.normpath(body)]"),
    ("M24 bare names in backticks judged",
     "            if tok and \"/\" in tok:\n                out.append(Mention(n, \"code\"",
     "            if tok:\n                out.append(Mention(n, \"code\""),
    ("M25 every fenced block read, whatever the language",
     "            if fence_lang not in SHELL_LANGS:\n                continue",
     "            if False:\n                continue"),
    ("M26 console output lines read as commands",
     "                if not pm:\n                    continue  # output, not a command",
     "                if not pm:\n                    pm = re.match(r\"^(.*)$\", line)"),
    ("M27 shell comments read",
     "            elif line.lstrip().startswith(\"#\"):\n                continue  # a comment",
     "            elif False:\n                continue  # a comment"),
    ("M28 a fence never closes",
     "            if len(s) >= len(in_fence) and s == in_fence[0] * len(s):",
     "            if False:"),
    ("M29 HTML comments read",
     "            line = re.sub(r\"<!--.*?-->\", \"\", line)",
     "            line = line"),
    ("M30 any branch in a github.com link judged",
     "                    if ref.lower() not in branches:\n                        continue",
     "                    if False:\n                        continue"),
    ("M31 links into other repositories judged",
     "                    if (\"%s/%s\" % (owner, name)).lower() != repo_slug.lower():\n                        continue",
     "                    if False:\n                        continue"),
    ("M32 links in include-fragments judged",
     "                if fragment and m.kind == \"link\":\n                    continue",
     "                if False:\n                    continue"),
    ("M33 `.claude/` and `.cursor/` read as this repository's",
     "                if m.kind in (\"code\", \"fence\") and top.startswith(\".\") and top not in self.tree.dirs:",
     "                if False:"),
    # levels
    ("M34 a sentence about the change stays an error",
     "            if level == \"error\" and HISTORICAL_RE.search(line.replace(m.text, \" \")):",
     "            if False:"),
    ("M35 the path's own words taken for the sentence's (`old/`)",
     "            if level == \"error\" and HISTORICAL_RE.search(line.replace(m.text, \" \")):",
     "            if level == \"error\" and HISTORICAL_RE.search(line):"),
    ("M36 SHORTENED not recognised",
     "                    target.rstrip(\"/\").endswith(\"/\" + body):",
     "                    False:"),
    ("M37 ELSEWHERE not recognised",
     "                tm = self.tree.tail_match(c)\n                if tm:",
     "                tm = None\n                if tm:"),
    ("M38 a relative link's fix given from the root",
     "                target_show = posixpath.relpath(target, posixpath.dirname(doc) or \".\")",
     "                target_show = target"),
    # exit status
    ("M39 a shallow clone passes",
     "    if ck.shallow and ck.unjudged:",
     "    if False:"),
    ("M40 no docs read passes",
     "    if ck.docs_read == 0:\n        print(\"moved-path-check: no docs were read\", file=sys.stderr)\n        return 2",
     "    if ck.docs_read == 0:\n        print(\"moved-path-check: no docs were read\", file=sys.stderr)\n        return 0"),
    ("M41 warnings fail the run",
     "    return 1 if errors else 0",
     "    return 1 if found else 0"),
    ("M42 no hint when one file of that name exists",
     "                same = self.tree.same_name(c)",
     "                same = None"),
    ("M43 git's quoted paths left quoted",
     "    if len(p) >= 2 and p[0] == '\"' and p[-1] == '\"':",
     "    if False:"),
]


def run_tests():
    r = subprocess.run([sys.executable, str(HERE / "test_moved_path_check.py")], capture_output=True, text=True,
                       cwd=str(HERE), timeout=900)
    return r.returncode == 0


def main():
    original = SRC.read_bytes().decode("utf-8")
    shutil.copyfile(SRC, BAK)
    survived = []
    try:
        if not run_tests():
            print("the unmutated suite fails; fix that first")
            return 2
        for name, old, new in MUTATIONS:
            if original.count(old) != 1:
                print("%-66s NOT APPLIED (pattern found %d times)" % (name, original.count(old)))
                survived.append(name)
                continue
            SRC.write_bytes(original.replace(old, new).encode("utf-8"))  # bytes: keep the line ends
            caught = not run_tests()
            print("%-66s %s" % (name, "caught" if caught else "SURVIVED"), flush=True)
            if not caught:
                survived.append(name)
    finally:
        SRC.write_bytes(original.encode("utf-8"))
        BAK.unlink()
    print("\n%d of %d mutations caught" % (len(MUTATIONS) - len(survived), len(MUTATIONS)))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
