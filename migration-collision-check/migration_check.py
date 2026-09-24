# -*- coding: utf-8 -*-
"""Find database migrations that collide: two files with one version, two leaves, two heads.

    python migration_check.py [path/to/repo]
    python migration_check.py path/to/repo --base origin/main     # what merging HEAD into it gives
    python migration_check.py path/to/repo --explain              # the sets it found and read

Reads the migration files of Flyway, Django, Alembic, Rails (Active Record) and golang-migrate,
and asks each set the question its own tool asks before it runs anything:

  Flyway          two versioned migrations with one version (1.1, 1_1 and 1.01 are the same)
  golang-migrate  two up (or two down) files with one version in a folder
  Rails           two migrations with one version, or with one name
  Django          an app with more than one leaf node; a dependency on a migration that is not there
  Alembic         more than one head; a down_revision that is not there; one revision id twice

With --base, it builds the tree a merge would give (the base branch, plus what this branch
added since the two split) and reports only what this branch brings in. That is where a
collision is born: each branch passes alone, the merge does not. It also reports a new Flyway
or golang-migrate migration numbered below one the base branch already has -- Flyway refuses it
by default (outOfOrder is false) and golang-migrate never applies it.

Nothing is executed, nothing is written, nothing is sent. Standard library only.
Exit code: 0 = no errors, 1 = errors, 2 = no migration set found (or git failed).
"""
import argparse
import ast
import os
import posixpath
import re
import subprocess
import sys

LEVEL = {"DUP": "error", "DUPNAME": "error", "DUPREV": "error", "CONFLICT": "error",
         "HEADS": "error", "MISSING": "error", "ORDER": "error",
         "DUP?": "warning", "HEADS?": "warning", "SCHEMA": "warning"}

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", ".env", "site-packages",
             "__pycache__", ".tox", ".nox", "vendor", "bower_components", "target", ".gradle",
             ".idea", "dist-packages"}

VENDORS = {"mysql", "mariadb", "postgres", "postgresql", "pg", "h2", "hsqldb", "oracle",
           "sqlserver", "mssql", "sqlite", "sqlite3", "db2", "derby", "cockroach",
           "cockroachdb", "redshift", "snowflake", "sybase", "informix", "firebird",
           "saphana", "hana", "tidb", "yugabyte", "yugabytedb", "clickhouse", "spanner"}


# ---------------------------------------------------------------- trees -------------------

class Tree:
    """A list of paths (posix, relative) and a way to read one. Origin says where a path came
    from when the tree is a simulated merge: 'shared', 'base' or 'branch'."""

    def __init__(self, paths, read, origin=None):
        self.paths = sorted(set(paths))
        self._read = read
        self._cache = {}
        self.origin = origin or {}

    def read(self, path):
        if path not in self._cache:
            try:
                self._cache[path] = self._read(path)
            except (OSError, UnicodeError):
                self._cache[path] = None
        return self._cache[path]


def local_tree(root):
    paths = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        rel = os.path.relpath(d, root).replace(os.sep, "/")
        for f in files:
            paths.append(f if rel == "." else rel + "/" + f)

    def read(p):
        with open(os.path.join(root, p), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return Tree(paths, read)


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout.decode("utf-8", "replace")


def git_paths(repo, ref):
    out = git(repo, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", ref)
    return [p for p in out.splitlines() if p and not (set(p.split("/")[:-1]) & SKIP_DIRS)]


def git_reader(repo, ref):
    def read(p):
        try:
            return git(repo, "show", "%s:%s" % (ref, p))
        except RuntimeError:
            return None
    return read


def merged_tree(base_paths, base_read, head_paths, head_read, split_paths=None, head_changed=()):
    """The tree a merge of head into base gives, for file lists. A path both sides have is read
    from base unless it is in head_changed (the branch edited it since the split). With
    split_paths (the merge base) a file the branch deleted is dropped; without it, the union
    of the two sides is used."""
    head_changed = set(head_changed)
    base, head = set(base_paths), set(head_paths)
    split = set(split_paths) if split_paths is not None else None
    if split is None:
        shared = base & head
        paths = base | head
        origin = {p: ("shared" if p in shared else "base" if p in base else "branch") for p in paths}
    else:
        removed = split - head
        added = head - split
        paths = (base - removed) | added
        origin = {}
        for p in paths:
            if p in split:
                origin[p] = "shared"
            elif p in added and p not in base:
                origin[p] = "branch"
            elif p in added:
                origin[p] = "shared"        # both sides added the same path
            else:
                origin[p] = "base"

    def read(p):
        return head_read(p) if origin.get(p) == "branch" or p in head_changed else base_read(p)
    return Tree(paths, read, origin)


# ---------------------------------------------------------------- findings ----------------

class Finding:
    def __init__(self, path, line, code, msg, involved):
        self.path, self.line, self.code, self.msg = path, line, code, msg
        self.involved = list(involved)

    def key(self):
        return (self.path, self.code, self.msg)

    def __repr__(self):
        return "%s:%d: %s %s %s" % (self.path, self.line, LEVEL[self.code], self.code, self.msg)


def pick(tree, paths):
    """The file to name first: one the branch brought in, if any."""
    paths = sorted(paths)
    for p in paths:
        if tree.origin.get(p) == "branch":
            return p
    return paths[0]


def fmt_others(paths, first):
    return ", ".join(p for p in sorted(paths) if p != first)


# ---------------------------------------------------------------- Flyway ------------------

FLYWAY = re.compile(r"^V(\d+(?:[._]\d+)*)__(.+)\.(sql|java|kt|scala|groovy)$")
CLASSPATH = re.compile(r"^(.*?)(?:^|/)src/(main|test)/(?:resources|java|kotlin|scala|groovy)/(.*)$")


def flyway_version(raw):
    """Flyway's own reading: '_' is '.', each part a number, trailing zero parts dropped."""
    parts = [int(x) for x in raw.replace("_", ".").split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def flyway_location(path):
    """Where Flyway sees the file: sql under src/main/resources and classes under src/main/java
    with the same package are one location."""
    d = posixpath.dirname(path)
    m = CLASSPATH.match(d + "/")
    if m:
        mod = m.group(1)
        return (mod + "/" if mod else "") + "src/%s/<classpath>/%s" % (m.group(2), m.group(3).rstrip("/"))
    return d


def flyway_sets(tree):
    sets = {}
    for p in tree.paths:
        name = posixpath.basename(p)
        m = FLYWAY.match(name)
        if not m:
            continue
        ext = m.group(3)
        if ext != "sql" and "/src/" not in "/" + p:
            continue                  # a class only counts on a JVM source path
        sets.setdefault(flyway_location(p), []).append((flyway_version(m.group(1)), m.group(1), p))
    return sets


def flyway_out_of_order(tree):
    """Files that turn Flyway's outOfOrder on. Returns the first path that does, or None."""
    pat = re.compile(r"(?i)(out[-_.]?of[-_.]?order)\s*[=:>]\s*\"?true")
    for p in tree.paths:
        b = posixpath.basename(p)
        if (b.startswith("flyway") and b.endswith((".conf", ".toml", ".properties"))) \
                or re.match(r"application[\w-]*\.(properties|ya?ml)$", b) \
                or b in ("pom.xml", "build.gradle", "build.gradle.kts"):
            t = tree.read(p) or ""
            if pat.search(t):
                return p
    return None


def check_flyway(tree, findings, stats):
    sets = flyway_sets(tree)
    for loc, items in sorted(sets.items()):
        stats["sets"]["flyway"] += 1
        stats["files"] += len(items)
        by = {}
        for v, raw, p in items:
            by.setdefault(v, []).append(p)
        for v, ps in sorted(by.items()):
            if len(ps) > 1:
                first = pick(tree, ps)
                findings.append(Finding(first, 1, "DUP", "Flyway version %s is also used by %s "
                                        "(Flyway stops: more than one migration with this version)"
                                        % (".".join(map(str, v)), fmt_others(ps, first)), ps))
    # the same version in sibling folders under one migration root (Flyway scans a location
    # recursively; folders named after a database are the usual one-location-per-vendor layout)
    roots = {}
    for loc, items in sets.items():
        parts = loc.split("/")
        idx = [i for i, x in enumerate(parts) if x in ("migration", "migrations")]
        if not idx or idx[-1] == len(parts) - 1:
            continue
        sub = parts[idx[-1] + 1]
        if sub.lower() in VENDORS:
            continue
        roots.setdefault("/".join(parts[:idx[-1] + 1]), []).append(loc)
    for root, locs in sorted(roots.items()):
        seen = {}
        for loc in locs:
            for v, raw, p in sets[loc]:
                seen.setdefault(v, set()).add((loc, p))
        shared = sorted(v for v, lp in seen.items() if len({l for l, _ in lp}) > 1)
        if not shared:
            continue
        # one line per root: a layout with one location per folder shares every version
        ps = sorted(p for v in shared for _, p in seen[v])
        folders = sorted({l[len(root) + 1:] + "/" for v in shared for l, _ in seen[v]})
        first = pick(tree, ps)
        shown = ", ".join(".".join(map(str, v)) for v in shared[:5]) + (", ..." if len(shared) > 5 else "")
        findings.append(Finding(first, 1, "DUP?", "%d Flyway version(s) (%s) are used in more than one "
                                "folder under %s: %s -- %d collision(s) if Flyway's location is %s itself "
                                "(it scans a location's subfolders), none if each folder is its own location"
                                % (len(shared), shown, root, ", ".join(folders), len(shared), root), ps))
    return sets


# ---------------------------------------------------------------- golang-migrate ----------

GOMIGRATE = re.compile(r"^([0-9]+)_(.*)\.(down|up)\.(.*)$")


def gomigrate_sets(tree):
    sets = {}
    for p in tree.paths:
        m = GOMIGRATE.match(posixpath.basename(p))
        if m and m.group(4) in ("sql", "cql", "json", "js", "cypher", "surql"):
            sets.setdefault(posixpath.dirname(p), []).append((int(m.group(1)), m.group(2), m.group(3), p))
    return sets


def pop_dialect(ident):
    """gobuffalo/pop names files <version>_<name>[.<dialect>][.autocommit].up.sql; a file for
    one dialect and a file for all of them do not collide (pop picks the dialect's own)."""
    parts = ident.lower().split(".")[1:]
    while parts and parts[-1] == "autocommit":
        parts.pop()
    if parts and (parts[-1] in VENDORS or parts[-1] == "all"):
        return parts[-1]
    return ""


def check_gomigrate(tree, findings, stats):
    sets = gomigrate_sets(tree)
    # the same file names are used by tools that order by the whole name, not by the number:
    # maragudk/migrate keeps "0001_create_table_a" and "0001_create_table_b" as two versions and
    # compares them as strings. When a go.mod requires it, a shared number is a warning.
    # (A go.mod that does not require golang-migrate is not enough: of the fixes replayed, 7 were
    # real golang-migrate collisions in such repositories -- the CLI, or a module elsewhere.)
    mods = [tree.read(p) or "" for p in tree.paths if posixpath.basename(p) == "go.mod"] if sets else []
    if any("github.com/maragudk/migrate" in m for m in mods):
        other = "a go.mod here requires maragudk/migrate, which orders by the whole file name"
    else:
        other = None
    for d, items in sorted(sets.items()):
        stats["sets"]["golang-migrate"] += 1
        stats["files"] += len(items)
        by = {}
        for v, ident, direction, p in items:
            by.setdefault((v, direction, pop_dialect(ident)), []).append(p)
        for (v, direction, dia), ps in sorted(by.items()):
            if len(ps) > 1:
                first = pick(tree, ps)
                if other:
                    findings.append(Finding(first, 1, "DUP?", "version %d (%s) is also used by %s "
                                            "(golang-migrate would stop; %s)"
                                            % (v, direction, fmt_others(ps, first), other), ps))
                    continue
                findings.append(Finding(first, 1, "DUP", "version %d (%s) is also used by %s "
                                        "(golang-migrate stops: duplicate migration file)"
                                        % (v, direction, fmt_others(ps, first)), ps))
    return sets


# ---------------------------------------------------------------- Rails -------------------

RAILS_DIR = re.compile(r"(^|/)db/(\w+_)?migrate(/|$)")
RAILS_FILE = re.compile(r"^([0-9]+)_([_a-z0-9]*)\.?([_a-z0-9]*)?\.rb$")
SCHEMA_VERSION = re.compile(r"ActiveRecord::Schema(?:\[[\d.]+\])?\.define\(\s*version:\s*([\d_]+)")


def rails_sets(tree):
    sets = {}
    for p in tree.paths:
        m = RAILS_DIR.search(p)
        if not m:
            continue
        root = p[:m.end() - 1] if m.group(3) == "/" else p
        m2 = RAILS_FILE.match(posixpath.basename(p))
        if m2:
            sets.setdefault(root, []).append((int(m2.group(1)), m2.group(2), p))
    return sets


def camelize(name):
    return "".join(x[:1].upper() + x[1:] for x in name.split("_"))


def check_rails(tree, findings, stats):
    sets = rails_sets(tree)
    gems = {posixpath.dirname(p) for p in tree.paths if p.endswith(".gemspec")}
    for root, items in sorted(sets.items()):
        m = re.search(r"(^|.*/)db/(\w+_)?migrate$", root)
        # an engine's migrations reach an app through install:migrations, which gives every
        # copy a new version; only an app that adds this folder to its own paths stops
        engine = m is not None and (m.group(1) or "").rstrip("/") in gems
        stats["sets"]["rails"] += 1
        stats["files"] += len(items)
        by_v, by_n = {}, {}
        for v, n, p in items:
            by_v.setdefault(v, []).append(p)
            by_n.setdefault(camelize(n), []).append(p)
        for n, ps in sorted(by_n.items()):
            if len(ps) > 1:
                first = pick(tree, ps)
                findings.append(Finding(first, 1, "DUPNAME", "migration name %s is also used by %s "
                                        "(Rails stops: DuplicateMigrationNameError)"
                                        % (n, fmt_others(ps, first)), ps))
        for v, ps in sorted(by_v.items()):
            if len(ps) > 1:
                first = pick(tree, ps)
                if engine:
                    findings.append(Finding(first, 1, "DUP?", "version %d is also used by %s, in an "
                                            "engine (install:migrations renumbers the copies; an app "
                                            "that loads this folder directly stops: "
                                            "DuplicateMigrationVersionError)"
                                            % (v, fmt_others(ps, first)), ps))
                    continue
                findings.append(Finding(first, 1, "DUP", "version %d is also used by %s "
                                        "(Rails stops: DuplicateMigrationVersionError)"
                                        % (v, fmt_others(ps, first)), ps))
        # db/migrate -> db/schema.rb, db/animals_migrate -> db/animals_schema.rb
        schema = (m.group(1) or "") + "db/" + (m.group(2) or "") + "schema.rb"
        text = tree.read(schema) if schema in tree.paths else None
        sm = SCHEMA_VERSION.search(text or "")
        if sm:
            sv = int(sm.group(1).replace("_", ""))
            newest = max(items)
            if newest[0] > sv:
                later = [p for v, n, p in items if v > sv]
                first = pick(tree, [newest[2]])
                findings.append(Finding(first, 1, "SCHEMA", "%d migration(s) newer than %s (version %d); "
                                        "the schema dump was not updated after them"
                                        % (len(later), schema, sv), [newest[2], schema]))
    return sets


# ---------------------------------------------------------------- Python parsing ----------

def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


TOP_ASSIGN = re.compile(r"^([A-Za-z_]\w*)[ \t]*(?::[^=\n]*)?=[ \t]*(\S)", re.M)


def assignments_by_text(text):
    """Module-level `name = literal` lines, for a file this Python cannot parse."""
    out = {}
    for m in TOP_ASSIGN.finditer(text):
        i = m.start(2)
        rhs = bracketed(text, i) if text[i] in "([{" else text[i:text.find("\n", i) % (len(text) + 1)]
        try:
            node = ast.parse(rhs.strip(), mode="eval").body
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            continue
        out.setdefault(m.group(1), (node, text.count("\n", 0, m.start()) + 1))
    return out


def module_assignments(text, stats=None):
    """{name: (value node, line)} for plain and annotated module-level assignments."""
    try:
        mod = ast.parse(text)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        if stats is not None:
            stats["by_text"] += 1
        return assignments_by_text(text), None
    out = {}
    for st in mod.body:
        if isinstance(st, ast.Assign):
            for t in st.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = (st.value, st.lineno)
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
            out[st.target.id] = (st.value, st.lineno)
    return out, mod


# ---------------------------------------------------------------- Django ------------------

def django_label(tree, app_dir):
    """The app label: AppConfig.label in the app's apps.py, else the folder's name."""
    apps = (app_dir + "/" if app_dir else "") + "apps.py"
    name = posixpath.basename(app_dir) if app_dir else ""
    if apps in tree.paths:
        text = tree.read(apps) or ""
        m = re.search(r"^\s+label\s*=\s*[\"']([\w.]+)[\"']", text, re.M)
        if m:
            return m.group(1)
    return name


PAIR = re.compile(r"""\(\s*(['"])([\w.]+)\1\s*,\s*(['"])([\w.]+)\3\s*,?\s*\)""")


def bracketed(text, i):
    """text[i] is an opening bracket: the text up to the one that closes it."""
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return text[i:]


def base_name(node):
    """`migrations.Migration` -> "Migration"; a class that is not Django's (PostHog's
    `AsyncMigrationDefinition`) does not end in Migration."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def django_by_text(text):
    """The same reading without a Python parser, for files written in a newer Python than the
    one this runs on (Python 3.14 allows `except A, B:`, which 3.13 cannot parse)."""
    m = re.search(r"^class\s+Migration\s*\(\s*(?:[\w.]*\.)?\w*Migration\s*[,)]", text, re.M)
    if not m:
        return None
    body = text[m.end():]
    got = {"dependencies": [], "run_before": [], "replaces": []}
    for name in got:
        a = re.search(r"^[ \t]+%s\s*(?::[^=\n]*)?=\s*([\[(])" % name, body, re.M)
        if a:
            got[name] = [(x[1], x[3]) for x in PAIR.findall(bracketed(body, a.start(1)))]
    return got["dependencies"], got["run_before"], got["replaces"], text.count("\n", 0, m.start()) + 1


def parse_django(text, stats=None):
    """(dependencies, run_before, replaces, line) from a migration's Migration class, or None
    when the file has no Migration class."""
    try:
        mod = ast.parse(text)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        got = django_by_text(text)
        if got is not None and stats is not None:
            stats["by_text"] += 1
        return got
    for st in mod.body:
        if isinstance(st, ast.ClassDef) and st.name == "Migration" and any(
                base_name(x).endswith("Migration") for x in st.bases):
            got = {"dependencies": [], "run_before": [], "replaces": []}
            for b in st.body:
                if isinstance(b, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and b.value is not None:
                    targets = b.targets if isinstance(b, ast.Assign) else [b.target]
                    for t in targets:
                        if not (isinstance(t, ast.Name) and t.id in got):
                            continue
                        # every literal (app, name) pair in the value: `[...] + settings.X` too
                        for e in ast.walk(b.value):
                            if isinstance(e, (ast.Tuple, ast.List)) and len(e.elts) == 2:
                                v = literal(e)
                                if isinstance(v, (tuple, list)) and all(isinstance(x, str) for x in v):
                                    got[t.id].append(tuple(v))
            return got["dependencies"], got["run_before"], got["replaces"], st.lineno
    return None


def why_unread(text):
    if text is None:
        return "could not be read"
    try:
        ast.parse(text)
    except (SyntaxError, ValueError) as e:
        return "does not parse: %s" % str(e).splitlines()[0][:80]
    return "no Migration class"


def check_django(tree, findings, stats):
    dirs = {}
    for p in tree.paths:
        d, b = posixpath.split(p)
        if posixpath.basename(d) == "migrations" and b.endswith(".py") and b[0] not in "_~" \
                and "." not in b[:-3]:        # a dotted name cannot be imported as a module
            dirs.setdefault(d, []).append(p)
    apps = {}        # label -> {name: (path, deps, run_before, replaces, line)}
    where = {}
    for d, files in sorted(dirs.items()):
        if d + "/__init__.py" not in tree.paths:
            continue                  # not a package: Django does not load it
        app_dir = posixpath.dirname(d)
        label = django_label(tree, app_dir)
        nodes, unread = {}, []
        for p in files:
            text = tree.read(p)
            got = parse_django(text or "", stats)
            if got is None:
                unread.append("%s (%s)" % (p, why_unread(text)))
                continue
            nodes[posixpath.basename(p)[:-3]] = (p,) + got
        if not nodes:
            continue                  # a folder named migrations that holds no Django migration
        stats["unread"] += len(unread)
        stats["unread_paths"] += unread
        if label in apps:             # two folders claim one label: keep them apart
            label = label + " (" + d + ")"
        apps[label] = nodes
        where[label] = d
        stats["sets"]["django"] += 1
        stats["files"] += len(nodes)
    # a squashed migration stands in for the ones it replaces, whether their files are still
    # there or were deleted (Django remaps a dependency on a replaced name to the squash when
    # none or all of the replaced ones are applied; that is the case this check assumes)
    replaced = {}
    for label, nodes in apps.items():
        replaced[label] = {}
        for n, (p, deps, rb, repl, line) in nodes.items():
            for a, r in repl:
                if a == label.split(" (")[0] and r != n:
                    replaced[label][r] = n
    for label, nodes in sorted(apps.items()):
        present = set(nodes)
        alias = replaced[label]
        live = {n for n in present if n not in alias}

        def res(n):
            seen = set()
            while n in alias and n not in seen:
                seen.add(n)
                n = alias[n]
            return n
        children = {n: set() for n in live}
        for n, (p, deps, rb, repl, line) in nodes.items():
            src = res(n)
            for a, dn in deps:
                if a != label.split(" (")[0]:
                    other = apps.get(a)
                    if other is not None and dn not in ("__first__", "__latest__") and dn not in other \
                            and dn not in replaced[a]:
                        findings.append(Finding(p, line, "MISSING", "depends on (%r, %r), and %s has no "
                                                "such migration (Django stops: NodeNotFoundError)"
                                                % (a, dn, where[a]), [p]))
                    continue
                if dn in ("__first__", "__latest__"):
                    continue
                if dn not in present and dn not in alias:
                    findings.append(Finding(p, line, "MISSING", "depends on (%r, %r), which is not in %s "
                                            "(Django stops: NodeNotFoundError)" % (a, dn, where[label]), [p]))
                    continue
                parent = res(dn)
                if parent != src and src in live:
                    children[parent].add(src)
            for a, dn in rb:
                if a == label.split(" (")[0] and (dn in present or dn in alias):
                    child = res(dn)
                    if child != src and src in live:
                        children[src].add(child)
        leaves = sorted(n for n in live if not children[n])
        if len(leaves) > 1:
            ps = [nodes[n][0] for n in leaves]
            first = pick(tree, ps)
            findings.append(Finding(first, nodes[posixpath.basename(first)[:-3]][4], "CONFLICT",
                                    "app %r has %d leaf migrations: %s (Django stops: Conflicting "
                                    "migrations detected; makemigrations --merge joins them)"
                                    % (label.split(" (")[0], len(leaves), ", ".join(leaves)), ps))
    return apps


# ---------------------------------------------------------------- Alembic -----------------

def as_ids(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (tuple, list, set, frozenset)):
        return [x for x in v if isinstance(x, str)]
    return []


def alembic_root(tree, d):
    """The script directory: the nearest folder above the revision file holding env.py."""
    cur = d
    while True:
        if (cur + "/" if cur else "") + "env.py" in tree.paths:
            return cur
        if not cur:
            return d
        cur = posixpath.dirname(cur)


def version_locations(tree):
    """Folders an alembic.ini names in version_locations (%(here)s is the ini's folder)."""
    out = set()
    for p in tree.paths:
        if posixpath.basename(p) != "alembic.ini":
            continue
        here = posixpath.dirname(p)
        for m in re.finditer(r"^version_locations\s*=\s*(.+)$", tree.read(p) or "", re.M):
            for tok in re.split(r"[\s,;:]+", m.group(1).replace("%(here)s", here or ".")):
                tok = posixpath.normpath(tok.strip().replace("\\", "/")).lstrip("./") if tok else ""
                if tok and not tok.startswith("%"):
                    out.add(tok)
    return out


def alembic_key(tree, d):
    """The script folder, split by a database-named folder under it (Prefect keeps one chain
    in versions/postgresql and another in versions/sqlite, each its own version location)."""
    root = alembic_root(tree, d)
    rel = d[len(root):].strip("/").split("/") if d.startswith(root) else []
    for part in rel:
        if part.lower() in VENDORS:
            return root + " [" + part + "]"
    return root


def check_alembic(tree, findings, stats):
    revs = {}           # root -> {rev: [(path, downs, labels, line)]}
    locs = version_locations(tree)
    for p in tree.paths:
        if not p.endswith(".py"):
            continue
        d, b = posixpath.split(p)
        if b in ("env.py", "__init__.py") or b.startswith("_"):
            continue
        # revision files live in a versions/ folder (Alembic's default) or a named version location
        if "versions" not in d.split("/") and not any(d == x or d.startswith(x + "/") for x in locs):
            continue
        text = tree.read(p)
        if not text or "down_revision" not in text:
            continue
        a, _ = module_assignments(text, stats)
        if not a or "revision" not in a or "down_revision" not in a:
            continue
        rv = literal(a["revision"][0])
        if not isinstance(rv, str):
            stats["unread"] += 1
            stats["unread_paths"].append(p)
            continue
        downs = as_ids(literal(a["down_revision"][0]))
        labels = as_ids(literal(a["branch_labels"][0])) if "branch_labels" in a else []
        root = alembic_key(tree, posixpath.dirname(p))
        revs.setdefault(root, {}).setdefault(rv, []).append((p, downs, labels, a["revision"][1]))
    everywhere = {}
    for root, m in revs.items():
        for rv, entries in m.items():
            everywhere.setdefault(rv, []).append(root)
    for root, m in sorted(revs.items()):
        stats["sets"]["alembic"] += 1
        stats["files"] += sum(len(v) for v in m.values())
        for rv, entries in sorted(m.items()):
            if len(entries) > 1:
                ps = [e[0] for e in entries]
                first = pick(tree, ps)
                findings.append(Finding(first, entries[0][3], "DUPREV", "revision %r is also in %s "
                                        "(Alembic only warns and keeps one of them)"
                                        % (rv, fmt_others(ps, first)), ps))
        # union-find over down_revision links: one component = one chain that should end once
        parent = {rv: rv for rv in m}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        referenced = set()
        for rv, entries in m.items():
            for p, downs, labels, line in entries:
                for dn in downs:
                    if dn in m:
                        referenced.add(dn)
                        parent[find(dn)] = find(rv)
                    elif dn not in everywhere:
                        findings.append(Finding(p, line, "MISSING", "down_revision %r is not in any "
                                                "revision file (Alembic warns, then cannot build the chain)"
                                                % dn, [p]))
        comps = {}
        for rv in m:
            comps.setdefault(find(rv), []).append(rv)
        for c, members in sorted(comps.items()):
            heads = sorted(rv for rv in members if rv not in referenced)
            if len(heads) > 1:
                labelled = any(e[2] for rv in members for e in m[rv])
                ps = [m[h][0][0] for h in heads]
                first = pick(tree, ps)
                line = m[heads[ps.index(first)]][0][3]
                findings.append(Finding(first, line, "HEADS?" if labelled else "HEADS",
                                        "%d heads in one chain: %s%s" % (
                                            len(heads), ", ".join("%s (%s)" % (h, m[h][0][0]) for h in heads),
                                            " -- branch_labels are used, so this may be on purpose"
                                            if labelled else " (alembic upgrade head stops: multiple "
                                            "heads; alembic merge heads joins them)"), ps))
    return revs


# ---------------------------------------------------------------- the order across a merge

def check_order(tree, findings, fly, gom, fly_ooo):
    """Base mode only: a migration this branch adds, numbered below one the base already has."""
    if fly_ooo is None:
        for loc, items in sorted(fly.items()):
            old = [(v, p) for v, raw, p in items if tree.origin.get(p) != "branch"]
            if not old:
                continue
            top = max(old)
            for v, raw, p in items:
                if tree.origin.get(p) == "branch" and v < top[0]:
                    findings.append(Finding(p, 1, "ORDER", "Flyway version %s is below %s (%s), which "
                                            "the base already has; a database that ran it refuses this "
                                            "one (outOfOrder is false by default)"
                                            % (".".join(map(str, v)), ".".join(map(str, top[0])), top[1]), [p]))
    for d, items in sorted(gom.items()):
        old = [(v, p) for v, ident, direction, p in items
               if tree.origin.get(p) != "branch" and direction == "up"]
        if not old:
            continue
        top = max(old)
        for v, ident, direction, p in items:
            if direction == "up" and tree.origin.get(p) == "branch" and v < top[0]:
                findings.append(Finding(p, 1, "ORDER", "version %d is below %d (%s), which the base "
                                        "already has; golang-migrate never applies a version below "
                                        "the current one" % (v, top[0], top[1]), [p]))


# ---------------------------------------------------------------- driver ------------------

def new_stats():
    return {"sets": {"flyway": 0, "golang-migrate": 0, "rails": 0, "django": 0, "alembic": 0},
            "files": 0, "unread": 0, "unread_paths": [], "by_text": 0, "ooo": None}


FIXTURE_DIRS = {"fixtures", "testdata", "__fixtures__", "test_fixtures"}


def without_fixtures(tree, stats):
    """Test fixtures are often broken on purpose: leave them out, and count what was left out."""
    keep, skipped = [], 0
    for p in tree.paths:
        if set(p.split("/")[:-1]) & FIXTURE_DIRS:
            b = posixpath.basename(p)
            if FLYWAY.match(b) or GOMIGRATE.match(b) or RAILS_FILE.match(b) or \
                    posixpath.basename(posixpath.dirname(p)) in ("migrations", "versions"):
                skipped += 1
            continue
        keep.append(p)
    stats["fixtures"] = skipped
    return Tree(keep, tree.read, tree.origin)


def check_tree(tree, order=False):
    findings, stats = [], new_stats()
    tree = without_fixtures(tree, stats)
    fly = check_flyway(tree, findings, stats)
    gom = check_gomigrate(tree, findings, stats)
    check_rails(tree, findings, stats)
    check_django(tree, findings, stats)
    check_alembic(tree, findings, stats)
    if order:
        stats["ooo"] = flyway_out_of_order(tree)
        check_order(tree, findings, fly, gom, stats["ooo"])
    findings.sort(key=lambda f: (f.path, f.line, f.code, f.msg))
    return findings, stats


def brought_in(tree, f):
    """In a merged tree: does this finding involve a file the branch added?"""
    return any(tree.origin.get(p) == "branch" for p in f.involved)


def summary(stats, errors, warnings, extra=""):
    sets = ", ".join("%s %d" % (k, v) for k, v in stats["sets"].items() if v)
    return "%d migration sets (%s), %d migration files read%s%s%s%s; %d errors, %d warnings" % (
        sum(stats["sets"].values()), sets or "none found", stats["files"],
        ", %d files not read (not a migration class, or ids not literal)" % stats["unread"]
        if stats["unread"] else "",
        ", %d under test fixture folders left out" % stats["fixtures"] if stats.get("fixtures") else "",
        ", %d read as text (newer Python syntax than this Python parses)" % stats["by_text"]
        if stats.get("by_text") else "",
        extra, errors, warnings)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--base", help="a git ref to merge into (e.g. origin/main)")
    ap.add_argument("--head", default="HEAD", help="with --base: the branch side (default HEAD)")
    ap.add_argument("--strict", action="store_true", help="warnings fail too")
    ap.add_argument("--explain", action="store_true", help="list the sets found")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    extra = ""
    try:
        if a.base:
            split = git(a.repo, "merge-base", a.base, a.head).strip()
            changed = git(a.repo, "-c", "core.quotepath=off", "diff", "--name-only",
                          "--diff-filter=M", split, a.head).splitlines()
            tree = merged_tree(git_paths(a.repo, a.base), git_reader(a.repo, a.base),
                               git_paths(a.repo, a.head), git_reader(a.repo, a.head),
                               git_paths(a.repo, split), changed)
        elif not os.path.isdir(a.repo):
            raise OSError("%s is not a folder" % a.repo)
        else:
            tree = local_tree(a.repo)
    except (RuntimeError, OSError) as e:
        print("stopped: %s" % e)
        return 2
    findings, stats = check_tree(tree, order=bool(a.base))
    if a.base:
        before = [f for f in findings if not brought_in(tree, f)]
        findings = [f for f in findings if brought_in(tree, f)]
        added = sum(1 for p in tree.paths if tree.origin.get(p) == "branch")
        extra = ", %d files added by %s since %s split from %s, %d finding(s) already on the base " \
                "not shown" % (added, a.head, split[:10], a.base, len(before))
        if stats["ooo"]:
            extra += ", ORDER not checked (outOfOrder is on in %s)" % stats["ooo"]
    if a.explain:
        for kind, n in stats["sets"].items():
            if n:
                print("# %s: %d set(s)" % (kind, n))
        for p in stats["unread_paths"]:
            print("# not read: %s" % p)
    for f in findings:
        print(f)
    errors = sum(1 for f in findings if LEVEL[f.code] == "error")
    warnings = len(findings) - errors
    print(summary(stats, errors, warnings, extra))
    if not sum(stats["sets"].values()):
        return 2
    return 1 if errors or (a.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
