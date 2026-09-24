# -*- coding: utf-8 -*-
"""Break migration_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- most of them are a place where the tool's own reading of the files
is easy to get wrong. The script runs the suite against each mutated copy and reports any
mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "migration_check.py"
BAK = HERE / "migration_check.py.mutation-backup"

MUTATIONS = [
    ("M1  Flyway versions compared as text (1_1 and 1.1 apart)",
     "    parts = [int(x) for x in raw.replace(\"_\", \".\").split(\".\")]",
     "    parts = [x for x in raw.split(\".\")]"),
    ("M2  trailing zero parts kept (2.0 and 2 apart)",
     "    while len(parts) > 1 and parts[-1] == 0:\n        parts.pop()",
     "    while False:\n        parts.pop()"),
    ("M3  sql and Java classes of one classpath location apart",
     "        return (mod + \"/\" if mod else \"\") + \"src/%s/<classpath>/%s\" % (m.group(2), m.group(3).rstrip(\"/\"))",
     "        return d"),
    ("M4  main and test resources merged",
     "        return (mod + \"/\" if mod else \"\") + \"src/%s/<classpath>/%s\" % (m.group(2), m.group(3).rstrip(\"/\"))",
     "        return (mod + \"/\" if mod else \"\") + \"src/main/<classpath>/%s\" % m.group(3).rstrip(\"/\")"),
    ("M5  vendor folders treated as one location",
     "        if sub.lower() in VENDORS:\n            continue",
     "        if False:\n            continue"),
    ("M6  a Java class anywhere counted",
     "        if ext != \"sql\" and \"/src/\" not in \"/\" + p:\n            continue",
     "        if False:\n            continue"),
    ("M7  ORDER reported for a version above the base's",
     "                if tree.origin.get(p) == \"branch\" and v < top[0]:",
     "                if tree.origin.get(p) == \"branch\" and v != top[0]:"),
    ("M8  outOfOrder=true ignored",
     "    if fly_ooo is None:",
     "    if True:"),
    ("M9  outOfOrder=false read as on",
     "    pat = re.compile(r\"(?i)(out[-_.]?of[-_.]?order)\\s*[=:>]\\s*\\\"?true\")",
     "    pat = re.compile(r\"(?i)(out[-_.]?of[-_.]?order)\")"),
    ("M10 golang-migrate up and down of one version collide",
     "            by.setdefault((v, direction, pop_dialect(ident)), []).append(p)",
     "            by.setdefault((v, pop_dialect(ident)), []).append(p)"),
    ("M11 pop dialects collide",
     "    if parts and (parts[-1] in VENDORS or parts[-1] == \"all\"):\n        return parts[-1]",
     "    if False:\n        return parts[-1]"),
    ("M12 golang-migrate folders merged",
     "            sets.setdefault(posixpath.dirname(p), []).append((int(m.group(1)), m.group(2), m.group(3), p))",
     "            sets.setdefault(\"\", []).append((int(m.group(1)), m.group(2), m.group(3), p))"),
    ("M13 golang-migrate ORDER dropped",
     "            if direction == \"up\" and tree.origin.get(p) == \"branch\" and v < top[0]:",
     "            if False:"),
    ("M14 Rails subfolders read as their own set",
     "        root = p[:m.end() - 1] if m.group(3) == \"/\" else p",
     "        root = posixpath.dirname(p)"),
    ("M15 Rails duplicate names not checked",
     "            by_n.setdefault(camelize(n), []).append(p)",
     "            by_n.setdefault(p, []).append(p)"),
    ("M16 schema.rb of a second database not found",
     "        schema = (m.group(1) or \"\") + \"db/\" + (m.group(2) or \"\") + \"schema.rb\"",
     "        schema = (m.group(1) or \"\") + \"db/schema.rb\""),
    ("M17 SCHEMA raised to an error",
     "         \"DUP?\": \"warning\", \"HEADS?\": \"warning\", \"SCHEMA\": \"warning\"}",
     "         \"DUP?\": \"warning\", \"HEADS?\": \"warning\", \"SCHEMA\": \"error\"}"),
    ("M18 Django migrations folder without __init__.py loaded",
     "        if d + \"/__init__.py\" not in tree.paths:\n            continue",
     "        if False:\n            continue"),
    ("M19 files starting with _ or ~ loaded",
     "        if posixpath.basename(d) == \"migrations\" and b.endswith(\".py\") and b[0] not in \"_~\" \\",
     "        if posixpath.basename(d) == \"migrations\" and b.endswith(\".py\") and b[0] not in \"_\" \\"),
    ("M20 AppConfig.label ignored",
     "        if m:\n            return m.group(1)\n    return name",
     "        if False:\n            return m.group(1)\n    return name"),
    ("M21 squashed migrations do not stand in for what they replace",
     "                if a == label.split(\" (\")[0] and r != n:\n                    replaced[label][r] = n",
     "                if False:\n                    replaced[label][r] = n"),
    ("M22 run_before ignored",
     "                    if child != src and src in live:\n                        children[src].add(child)",
     "                    if False:\n                        children[src].add(child)"),
    ("M23 cross-app dependencies read as edges in the app",
     "                if a != label.split(\" (\")[0]:",
     "                if False:"),
    ("M24 missing same-app dependency not reported",
     "                if dn not in present and dn not in alias:\n                    findings.append(",
     "                if dn not in present and dn not in alias:\n                    continue\n                    findings.append("),
    ("M25 missing dependency in another app of the repo not reported",
     "                    if other is not None and dn not in (\"__first__\", \"__latest__\") and dn not in other \\",
     "                    if False and dn not in other \\"),
    ("M26 a Django fork not reported",
     "        if len(leaves) > 1:\n            ps = [nodes[n][0] for n in leaves]",
     "        if len(leaves) > 2:\n            ps = [nodes[n][0] for n in leaves]"),
    ("M27 Alembic annotated assignments not read",
     "        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:",
     "        elif False:"),
    ("M28 Alembic merge revisions read as one parent",
     "    if isinstance(v, (tuple, list, set, frozenset)):\n        return [x for x in v if isinstance(x, str)]",
     "    if isinstance(v, (tuple, list, set, frozenset)):\n        return [x for x in v if isinstance(x, str)][:1]"),
    ("M29 Alembic environments merged",
     "        if (cur + \"/\" if cur else \"\") + \"env.py\" in tree.paths:\n            return cur",
     "        if False:\n            return cur"),
    ("M30 every Python file read as a revision",
     "        if \"versions\" not in d.split(\"/\") and not any(d == x or d.startswith(x + \"/\") for x in locs):",
     "        if False:"),
    ("M31 branch_labels ignored (a labelled fork an error)",
     "                labelled = any(e[2] for rv in members for e in m[rv])",
     "                labelled = False"),
    ("M32 separate bases read as one chain",
     "                        parent[find(dn)] = find(rv)",
     "                        parent[find(dn)] = find(rv)\n                parent[find(rv)] = find(next(iter(m)))"),
    ("M33 Alembic duplicate revision not reported",
     "            if len(entries) > 1:\n                ps = [e[0] for e in entries]",
     "            if len(entries) > 9:\n                ps = [e[0] for e in entries]"),
    ("M34 Alembic missing down_revision not reported",
     "                    elif dn not in everywhere:",
     "                    elif False:"),
    ("M35 non-literal revision not counted",
     "        if not isinstance(rv, str):\n            stats[\"unread\"] += 1\n",
     "        if not isinstance(rv, str):\n"),
    ("M36 merge: a file the branch deleted kept",
     "        removed = split - head",
     "        removed = set()"),
    ("M37 merge: a file the branch edited read from the base",
     "        return head_read(p) if origin.get(p) == \"branch\" or p in head_changed else base_read(p)",
     "        return head_read(p) if origin.get(p) == \"branch\" else base_read(p)"),
    ("M38 base mode blames the branch for what the base already had",
     "    return any(tree.origin.get(p) == \"branch\" for p in f.involved)",
     "    return True"),
    ("M39 the file named first is not the branch's",
     "        if tree.origin.get(p) == \"branch\":\n            return p\n    return paths[0]",
     "        if False:\n            return p\n    return paths[0]"),
    ("M40 no migration set found reported as a pass",
     "    if not sum(stats[\"sets\"].values()):\n        return 2",
     "    if False:\n        return 2"),
    ("M41 Flyway duplicates not reported",
     "            if len(ps) > 1:\n                first = pick(tree, ps)\n                findings.append(Finding(first, 1, \"DUP\", \"Flyway",
     "            if len(ps) > 2:\n                first = pick(tree, ps)\n                findings.append(Finding(first, 1, \"DUP\", \"Flyway"),
    ("M42 Alembic heads not reported",
     "            if len(heads) > 1:",
     "            if len(heads) > 2:"),
    # added with the fixes after the first 53 commits
    ("M43 a dotted file name in migrations/ read as a migration",
     "                and \".\" not in b[:-3]:",
     "                and True:"),
    ("M44 DUP? across sibling folders not reported",
     "        if not shared:\n            continue",
     "        if True:\n            continue"),
    # added with the fixes after the first 50 repositories
    ("M45 a dependency on a name another app's squash replaced reported missing",
     "                            and dn not in replaced[a]:",
     "                            and True:"),
    ("M46 a dependency on a deleted, replaced name in the app reported missing",
     "                if dn not in present and dn not in alias:",
     "                if dn not in present:"),
    ("M47 run_before naming a replaced migration ignored",
     "                if a == label.split(\" (\")[0] and (dn in present or dn in alias):",
     "                if a == label.split(\" (\")[0] and dn in present:"),
    ("M48 pop's .autocommit read as the dialect",
     "    while parts and parts[-1] == \"autocommit\":\n        parts.pop()",
     "    while False:\n        parts.pop()"),
    ("M49 a Rails engine's duplicate version reported as an error",
     "        engine = m is not None and (m.group(1) or \"\").rstrip(\"/\") in gems",
     "        engine = False"),
    ("M50 any gemspec in the repository makes every folder an engine",
     "        engine = m is not None and (m.group(1) or \"\").rstrip(\"/\") in gems",
     "        engine = bool(gems)"),
    ("M51 test fixture folders read",
     "        if set(p.split(\"/\")[:-1]) & FIXTURE_DIRS:",
     "        if False:"),
    # added with the fixes for files in newer Python syntax
    ("M52 a Django migration this Python cannot parse dropped",
     "        got = django_by_text(text)\n",
     "        got = None\n"),
    ("M53 an Alembic revision this Python cannot parse dropped",
     "        return assignments_by_text(text), None",
     "        return None, None"),
    ("M55 dependencies written as `[...] + settings.X` not read",
     "                        for e in ast.walk(b.value):",
     "                        for e in (b.value.elts if isinstance(b.value, ast.List) else []):"),
    # added with the fixes after the held-out halves
    ("M56 any class named Migration read as Django's",
     "                base_name(x).endswith(\"Migration\") for x in st.bases):",
     "                True for x in st.bases):"),
    ("M57 files of a folder with no Django migration counted as unread",
     "        if not nodes:\n            continue                  # a folder named migrations that holds no Django migration\n        stats[\"unread\"] += len(unread)",
     "        stats[\"unread\"] += len(unread)\n        if not nodes:\n            continue"),
    ("M58 alembic.ini version_locations not read",
     "                if tok and not tok.startswith(\"%\"):\n                    out.add(tok)",
     "                if False:\n                    out.add(tok)"),
    ("M59 database-named Alembic folders read as one chain",
     "        if part.lower() in VENDORS:\n            return root + \" [\" + part + \"]\"",
     "        if False:\n            return root + \" [\" + part + \"]\""),
    ("M60 go.mod ignored (every shared number an error)",
     "        other = None",
     "        other = None\n    other = None"),
    ("M61 maragudk/migrate not recognised",
     "    if any(\"github.com/maragudk/migrate\" in m for m in mods):",
     "    if False:"),
    ("M62 any go.mod downgrades a shared number",
     "    if any(\"github.com/maragudk/migrate\" in m for m in mods):",
     "    if mods:"),
    ("M54 a multi-line value in the text reading cut at the line end",
     "        rhs = bracketed(text, i) if text[i] in \"([{\" else",
     "        rhs = text[i:text.find(\"\\n\", i)] if False else"),
]


def run_tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_migration_check"],
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
