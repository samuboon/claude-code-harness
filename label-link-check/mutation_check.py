# -*- coding: utf-8 -*-
"""Break label_link_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- most of them are a place where reading a GitHub search link is easy
to get wrong (case compared, `%20` not decoded, quotes not honoured, `&amp;` left in, a nested
`labels:` key taken for the template's own). The script runs the suite against each mutated copy
and reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "label_link_check.py"
BAK = HERE / "label_link_check.py.mutation-backup"

MUTATIONS = [
    # labels
    ("M1  label names compared with case",
     "        return name.lower() in self.lower",
     "        return name in self.names"),
    ("M2  suggestion key keeps dashes, spaces and emoji",
     "    return re.sub(r\"[\\W_]+\", \"\", name.lower(), flags=re.UNICODE)",
     "    return name.lower()"),
    ("M3  case-only difference not reported",
     "        if ls.has(label):\n            if not ls.exact(label):",
     "        if ls.has(label):\n            if False:"),
    ("M3b a label list cut at the page limit used as if complete",
     "                self._labels[key] = None\n                return None\n            st, data",
     "                break\n            st, data"),
    ("M4  a repository that is gone reported as unreadable",
     "        return self.source.exists(repo) is False",
     "        return False"),
    # links
    ("M5  %20 in a /labels/ path not decoded",
     "        label = urllib.parse.unquote(raw)",
     "        label = raw"),
    ("M6  &amp; left in an HTML href",
     "    u = html.unescape(u)",
     "    u = u"),
    ("M6b an AsciiDoc url[text] read as one URL",
     "github\\.com/[^\\s<>\\\"'`\\[\\]\\)\\}|\\\\]+\", re.I)",
     "github\\.com/[^\\s<>\\\"'`\\]\\)\\}|\\\\]+\", re.I)"),
    ("M7  a full stop after the link taken into the label",
     "    while u and u[-1] in \".,;:!?*_~'\\\"\":",
     "    while False:"),
    ("M8  `+` in a path read as a space silently",
     "        if \"+\" in label and ls.has(label.replace(\"+\", \" \")):",
     "        if False:"),
    ("M9  ?labels= not read",
     "            for lv in qs.get(\"labels\", []):",
     "            for lv in []:"),
    ("M10 ?template= not checked",
     "                if tv not in names:",
     "                if False:"),
    ("M10b template=BLANK_ISSUE taken for a file name",
     "                if not tv or tv == \"BLANK_ISSUE\":",
     "                if not tv:"),
    ("M11 no template folder at a repository root read as 'cannot tell'",
     "    if (root / \".git\").exists() or (root / \".github\").is_dir():\n        return []",
     "    if (root / \".git\").exists() or (root / \".github\").is_dir():\n        return None"),
    ("M12 repo: in the query ignored",
     "    target = repos[0] if len(repos) == 1 else (default_repo if not repos else None)",
     "    target = default_repo"),
    ("M11b a repository with no template folder not given its owner's .github templates",
     "        if names == [] and self.source is not None and hasattr(self.source, \"org_templates\"):",
     "        if False:"),
    ("M11c a template renamed with an ordering prefix not suggested",
     "                        sug = hits[0] if len(hits) == 1 else \"\"",
     "                        sug = \"\""),
    ("M11d quotes inside a /labels/ path read as an ordinary missing label",
     "        if '\"' in label:\n            # the label page",
     "        if False:\n            # the label page"),
    ("M11e a Markdown link target cut at its first quote",
     "        for m in MD_TARGET_RE.finditer(line):\n            spans.append",
     "        for m in []:\n            spans.append"),
    ("M11f the closing quote of a URL stripped as punctuation",
     "        if u[-1] in \"'\\\"\" and u.count(u[-1]) % 2 == 0:\n            break",
     "        if False:\n            break"),
    # queries
    ("M13 quotes not honoured when splitting a query",
     "        if ch == '\"':\n            inq = not inq\n            cur += ch",
     "        if ch == '\"':\n            cur += ch"),
    ("M14 comma (OR) not split",
     "        elif ch == \",\" and not inq:",
     "        elif False:"),
    ("M15 unquoted multi-word label not recognised",
     "                if found:\n                    real",
     "                if False:\n                    real"),
    ("M16 -label: for a missing label reported as an error",
     "            if neg:\n                emit(\"warning\", \"NEG_LABEL\"",
     "            if False:\n                emit(\"warning\", \"NEG_LABEL\""),
    ("M16b a missing label in an OR list next to one that exists reported as an error",
     "            elif len(vals) > 1 and any(ls.has(x) for x, _ in vals):",
     "            elif False:"),
    ("M16c every label in an OR list missing reported only as a warning",
     "            elif len(vals) > 1 and any(ls.has(x) for x, _ in vals):",
     "            elif len(vals) > 1:"),
    ("M16d title: taken for an unknown qualifier",
     "\"author-app\", \"title\", \"body\",",
     "\"author-app\", \"body\","),
    ("M17 unknown qualifier passed silently",
     "        if qual not in KNOWN_QUALIFIERS:",
     "        if False:"),
    ("M18 is: value not checked",
     "                if v.lower() not in IS_VALUES:",
     "                if False:"),
    ("M19 grouping parentheses kept on the token",
     "    while tok.startswith(\"(\"):\n        tok = tok[1:]",
     "    while False:\n        tok = tok[1:]"),
    # templates
    ("M20 a nested `labels:` key read as the template's",
     "        m = re.match(r\"^labels\\s*:(.*)$\", line)",
     "        m = re.match(r\"^\\s*labels\\s*:(.*)$\", line)"),
    ("M21 comment after a block-list item kept",
     "                v = _unq(_strip_comment(mm.group(1)))",
     "                v = _unq(mm.group(1))"),
    ("M21b a comma inside a block-list item not split",
     "                for part in v.split(\",\"):\n                    if part.strip():\n                        out.append((kk + 1",
     "                for part in [v]:\n                    if part.strip():\n                        out.append((kk + 1"),
    ("M22 Markdown body read past the front matter",
     "            if lines[k].strip() in (\"---\", \"...\"):\n                end = k",
     "            if lines[k].strip() in (\"---\", \"...\"):\n                end = len(lines)"),
    ("M23 config.yml read as a template",
     "in_tpl and not fp.name.lower().startswith(\"config.\"))",
     "in_tpl)"),
    ("M24 template labels that exist reported anyway",
     "        if ls.has(lab):\n            if not ls.exact(lab):",
     "        if False:\n            if not ls.exact(lab):"),
    # walking and exit status
    ("M25 node_modules walked",
     "sorted(d for d in dirnames if d not in SKIP_DIRS and not",
     "sorted(d for d in dirnames if not"),
    ("M26 the same finding twice on one line",
     "        if k not in seen:\n            seen.add(k)",
     "        if True:\n            seen.add(k)"),
    ("M27 exit 0 when nothing was read",
     "    if files == 0:",
     "    if False:"),
    ("M28 exit 0 when the repository's own labels could not be read",
     "    if own_unreadable:",
     "    if False:"),
    ("M29 exit 0 on errors",
     "    if errors:\n        return 1",
     "    if False:\n        return 1"),
]


def run_tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_label_link_check"],
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
