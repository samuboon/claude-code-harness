# -*- coding: utf-8 -*-
"""Check the setup steps in a README against the repository they describe, without running them.

    python setup_doc_check.py [ROOT]                 # README*, CONTRIBUTING*, docs/*setup*, ...
    python setup_doc_check.py ROOT --doc docs/dev.md # these documents only
    python setup_doc_check.py ROOT --tsv             # one row per finding

It reads the shell commands in the documents (fenced blocks, and inline code that starts with a
known tool) and the prose that states a language version, follows `cd` through them, and asks
the repository, never the shell:

  SCRIPT   `npm run X` / `pnpm run X`, and X is not in the nearest package.json's "scripts"
  TARGET   `make X`, and no rule in that Makefile (or the files it includes) makes X
  PATH     a file or folder the command needs (cd, cp, source, ./x, python x.py, pip -r x,
           docker compose -f x, ...) is not in the repository and nothing earlier made it
  NOPROJ   `npm run` with no package.json above it, `make` with no Makefile, `docker compose`
           with no compose file
  VERSION  the document says an older language version than the repository requires
           (engines.node, requires-python, go.mod, Java release, Gemfile ruby, rust-version)

Standard library only. Reads files, writes nothing, runs nothing, no network.
Exit 0 = no error, 1 = at least one error, 2 = nothing to read.
"""
import argparse
import copy
import difflib
import fnmatch
import json
import os
import posixpath
import re
import shlex
import sys

LEVEL = {
    "SCRIPT": "error", "TARGET": "error", "PATH": "error", "NOPROJ": "error", "VERSION": "error",
    "SCRIPT?": "warning", "TARGET?": "warning", "PATH?": "warning", "VERSION?": "warning",
    "PINS": "warning",
}

DOC_PATTERNS = [
    "readme*.md", "readme*.markdown", "contributing*.md", "development*.md", "develop*.md",
    "hacking*.md", "install*.md", "building*.md", "build*.md", "setup*.md", "getting*started*.md",
    "quickstart*.md", "onboarding*.md",
]
DOC_DIRS = ["", "docs", "doc", ".github"]

SHELL_LANGS = {"sh", "bash", "shell", "zsh", "console", "shell-session", "shellsession", "terminal",
               "bash-session", "sh-session", "shell-script", "fish", "powershell", "pwsh", "ps1",
               "ps", "cmd", "bat", "batch", "command", "commandline", "cli", "text", "txt", "plain",
               "plaintext", "none", ""}
PROMPTED_LANGS = {"console", "shell-session", "shellsession", "terminal", "bash-session",
                  "sh-session", "text", "txt", "plain", "plaintext", "none"}
TOOLS = {"npm", "yarn", "pnpm", "bun", "make", "cd", "cp", "pip", "pip3", "python", "python3", "py",
         "source", ".", "bash", "sh", "zsh", "docker", "docker-compose", "poetry", "conda", "mamba",
         "node", "nvm", "pyenv", "uv", "mkdir", "touch", "git", "brew", "fnm", "volta", "sdk",
         "asdf", "rustup", "go", "cargo", "mvn", "gradle", "bundle", "ruby"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case",
            "esac", "function", "{", "}", "(", ")", "!", "[", "[[", "export", "set", "alias",
            "echo", "printf", "read", "test", "return", "exit", "unset", "local"}
PREFIXES = {"sudo", "env", "time", "exec", "command", "nohup", "nice", "builtin"}
OPS = {"&&", "||", ";", "|", "&", ";;", "|&"}
BUILD_WORDS = re.compile(r"\b(build|compile|dist|bundle|package|generate|gen|codegen|install|setup|"
                         r"bootstrap|prepare|tsc|cmake|gradle|mvn|cargo|go build|make)\b")
YARN_BUILTINS = set("""add audit autoclean bin cache check config constraints create dedupe dlx
exec explain generate-lock-entry global help import info init install licenses link list login logout
node npm outdated owner pack patch patch-commit plugin policies publish rebuild remove run search set
tag team unlink unplug up upgrade upgrade-interactive version versions why workspace workspaces
""".split())
PNPM_BUILTINS = set("""add install i update up upgrade remove rm uninstall un link ln unlink import
rebuild rb prune fetch install-test it patch patch-commit patch-remove audit list ls outdated why
licenses run exec test t start dlx create env setup store root bin config c init deploy doctor
publish pack recursive server self-update approve-builds ignored-builds catalog cat-file
""".split())
NPM_LIFECYCLE = {"test": "test", "t": "test", "tst": "test", "start": "start", "stop": "stop",
                 "restart": "restart"}
COMPOSE_FILES = ["compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"]
MAKEFILES = ["GNUmakefile", "makefile", "Makefile"]
GENERATES_MAKEFILE = ["CMakeLists.txt", "configure", "configure.ac", "Makefile.am", "Makefile.in",
                      "Makefile.PL", "meson.build"]
PLACEHOLDER = "\x00PH\x00"
# (command, subcommand) -> how many positional arguments come before the new folder's name
PROJECT_MAKERS = {("uv", "init"): 0, ("cargo", "new"): 0, ("poetry", "new"): 0, ("rails", "new"): 0,
                  ("django-admin", "startproject"): 0, ("dotnet", "new"): 1, ("npm", "create"): 1,
                  ("pnpm", "create"): 1, ("yarn", "create"): 1, ("bun", "create"): 1,
                  ("npx", "create-react-app"): 0, ("npx", "create-next-app"): 0, ("hatch", "new"): 0,
                  ("go", "mod"): 99, ("pdm", "init"): 99, ("npm", "init"): 1}
CLONE_VALUE_OPTIONS = {"-b", "--branch", "--depth", "-o", "--origin", "--reference", "-c", "--config",
                       "-j", "--jobs", "--separate-git-dir", "--shallow-since", "--shallow-exclude",
                       "--template", "-u", "--upload-pack", "--filter", "--server-option"}


# --------------------------------------------------------------------------- the repository

class LocalRepo:
    """The working tree on disk."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.name = os.path.basename(self.root.rstrip("/\\"))

    def _p(self, rel):
        return os.path.join(self.root, *rel.split("/")) if rel else self.root

    def exists(self, rel):
        return os.path.exists(self._p(rel))

    def isdir(self, rel):
        return os.path.isdir(self._p(rel))

    def read(self, rel):
        try:
            with open(self._p(rel), "rb") as f:
                return f.read().decode("utf-8", "replace")
        except OSError:
            return None

    def listdir(self, rel):
        try:
            return os.listdir(self._p(rel))
        except OSError:
            return []

    def _all(self):
        if not hasattr(self, "_files"):
            self._files = []
            for d, dirs, files in os.walk(self.root):
                dirs[:] = [x for x in dirs if x not in (".git", "node_modules")]
                for f in files:
                    self._files.append(os.path.relpath(os.path.join(d, f), self.root).replace("\\", "/"))
        return self._files

    def named(self, name):
        return sorted(p for p in self._all() if p.rsplit("/", 1)[-1] == name)

    def ending(self, tail):
        return sorted(p for p in self._all() if p.endswith("/" + tail))


class TreeRepo:
    """A repository seen through a list of paths and a function that reads one (used by replay)."""

    def __init__(self, paths, reader, name=""):
        self.files = set(paths)
        self.dirs = {""}
        for p in self.files:
            parts = p.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.reader = reader
        self.name = name
        self.cache = {}

    def exists(self, rel):
        return rel in self.files or rel in self.dirs

    def isdir(self, rel):
        return rel in self.dirs

    def read(self, rel):
        if rel not in self.files:
            return None
        if rel not in self.cache:
            self.cache[rel] = self.reader(rel)
        return self.cache[rel]

    def named(self, name):
        return sorted(p for p in self.files if p.rsplit("/", 1)[-1] == name
                      and "node_modules" not in p.split("/"))

    def ending(self, tail):
        return sorted(p for p in self.files if p.endswith("/" + tail))

    def listdir(self, rel):
        pre = rel + "/" if rel else ""
        out = set()
        for p in self.files | self.dirs:
            if p and p.startswith(pre) and "/" not in p[len(pre):]:
                out.add(p[len(pre):])
        return sorted(out)


def find_docs(repo):
    docs = []
    for d in DOC_DIRS:
        if d and not repo.isdir(d):
            continue
        for n in sorted(repo.listdir(d), key=lambda n: (not n.lower().startswith("readme"), n.lower())):
            rel = (d + "/" if d else "") + n
            if repo.isdir(rel):
                continue
            if any(fnmatch.fnmatch(n.lower(), p) for p in DOC_PATTERNS):
                docs.append(rel)
    return docs


# --------------------------------------------------------------------------- .gitignore

class Ignore:
    def __init__(self, repo):
        self.repo = repo
        self.cache = {}

    def _rules(self, d):
        if d not in self.cache:
            text = self.repo.read((d + "/" if d else "") + ".gitignore") or ""
            rules = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                anchored = "/" in line.rstrip("/")
                rules.append((line.strip("/"), anchored))
            self.cache[d] = rules
        return self.cache[d]

    def ignored(self, rel):
        parts = rel.split("/")
        for i in range(len(parts)):
            base = "/".join(parts[:i])
            for j in range(i + 1, len(parts) + 1):
                sub = "/".join(parts[i:j])
                for pat, anchored in self._rules(base):
                    if anchored:
                        if fnmatch.fnmatch(sub, pat) or fnmatch.fnmatch(sub, pat.replace("**/", "")):
                            return True
                    elif fnmatch.fnmatch(parts[j - 1], pat):
                        return True
        return False


# --------------------------------------------------------------------------- markdown

FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^`\s{]*)")
INLINE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


def read_markdown(text):
    """Yield ("code", lang, lineno, line) for lines in fenced blocks, ("prose", None, lineno, line)
    for the rest, and ("heading", ...) for headings."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m and m.group(2)[0] == "`" and "`" in lines[i][m.end(2):]:
            m = None      # ```npm run dev``` on one line is inline code, not a fence
        if m:
            indent, fence, lang = len(m.group(1)), m.group(2), m.group(3).lower()
            lang = lang.split(",")[0]
            j = i + 1
            yield ("open", lang, i + 1, lines[i])
            while j < len(lines):
                s = lines[j]
                close = re.match(r"^\s*(%s{%d,})\s*$" % (re.escape(fence[0]), len(fence)), s)
                if close:
                    break
                cut = 0
                while cut < indent and cut < len(s) and s[cut] == " ":
                    cut += 1
                yield ("code", lang, j + 1, s[cut:])
                j += 1
            i = j + 1
            continue
        kind = "heading" if HEADING.match(lines[i]) else "prose"
        yield (kind, None, i + 1, lines[i])
        i += 1


# --------------------------------------------------------------------------- shell lines

PROMPT = re.compile(r"^(?:\(\S+\)\s*)?(?:[\w.@-]+[@:][^\s$#>]*)?(\$|PS>|PS [^>]*>|>(?!>))\s+\S")


def logical_lines(block, prompted):
    """block: list of (lineno, text). Join continuations, strip prompts, drop heredoc bodies.
    Returns (lineno, command, whether it was written after a prompt)."""
    out = []
    buf, start, had = "", None, False
    heredoc = None
    if any(PROMPT.match(raw.lstrip()) for _n, raw in block):
        prompted = True     # a block that shows prompts shows output on the other lines
    for lineno, raw in block:
        s = raw.rstrip()
        if heredoc is not None:
            if s.strip() == heredoc:
                heredoc = None
            continue
        if not buf:
            stripped = s.lstrip()
            m = re.match(r"^(?:\(\S+\)\s*)?(?:[\w.@-]+[@:][^\s$#>]*)?(\$|%|>|PS>|PS [^>]*>)\s(.*)$",
                         stripped)
            had = bool(m and not stripped.startswith(">>"))
            if had:
                s = m.group(2)
            elif prompted:
                continue          # output, not a command
            start = lineno
        cont = False
        for mark in ("\\", "`", "^"):
            if s.endswith(mark) and not s.endswith(mark * 2):
                s = s[:-1]
                cont = True
                break
        buf = (buf + " " + s.strip()) if buf else s.strip()
        hm = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", s)
        if hm:
            heredoc = hm.group(1)
        if not cont:
            if buf:
                out.append((start, buf, had))
            buf = ""
    if buf:
        out.append((start, buf, had))
    return out


def split_commands(line):
    """Return a list of token lists, or None when the line is not safe to read."""
    if "$(" in line or "`" in line:
        return None
    line = re.sub(r"<<-?\s*['\"]?\w+['\"]?", " ", line)      # the body was dropped already
    line = re.sub(r"<[A-Za-z][\w .:/-]*>", PLACEHOLDER, line)
    line = re.sub(r"\[[A-Za-z][\w .-]*\]", lambda m: m.group(0) if m.start() and
                  line[m.start() - 1] not in " \t" else PLACEHOLDER, line)
    lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    lex.commenters = "#"
    try:
        tokens = list(lex)
    except ValueError:
        return None
    cmds, cur = [], []
    for t in tokens:
        if t in OPS or (t and set(t) <= set(";&|")):
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        cmds.append(cur)
    return cmds


def is_pathlike(tok):
    if not tok or tok.startswith("-") or "://" in tok or PLACEHOLDER in tok:
        return False
    if any(c in tok for c in "$*?~%{}@:=\"'<>|\\") and not tok.startswith(".\\"):
        return False
    if tok.startswith("/") or re.match(r"^[A-Za-z]:", tok):
        return False
    if re.search(r"(^|/)(path/to(/|$)|your[-_]|my[-_]|some[-_]|example(/|$)|foo([/._-]|$))", tok, re.I) \
            or re.search(r"XXX|xxx|\.\.\.|…", tok):
        return False
    return True


def norm(cwd, tok):
    tok = tok.replace("\\", "/")
    p = posixpath.normpath(posixpath.join(cwd, tok)) if cwd else posixpath.normpath(tok)
    if p == ".":
        return ""
    if p == ".." or p.startswith("../"):
        return None
    return p


# --------------------------------------------------------------------------- package.json / Makefile

def nearest(repo, cwd, names):
    d = cwd
    while True:
        for n in names:
            rel = (d + "/" if d else "") + n
            if repo.exists(rel) and not repo.isdir(rel):
                return rel
        if not d:
            return None
        d = posixpath.dirname(d)


def load_package(repo, rel):
    try:
        data = json.loads(repo.read(rel) or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def dep_names(pkg):
    names = set()
    for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        v = pkg.get(k)
        if isinstance(v, dict):
            for n in v:
                names.add(n)
                names.add(n.rsplit("/", 1)[-1])
    return names


MAKE_RULE = re.compile(r"^([^\s#=:\t][^#=:]*?)\s*(::?)(?!=)")


def make_targets(repo, rel, seen=None):
    """Return (targets, patterns, complete)."""
    seen = seen if seen is not None else set()
    if rel in seen:
        return set(), [], True
    seen.add(rel)
    text = repo.read(rel)
    if text is None:
        return set(), [], False
    targets, patterns, complete = set(), [], True
    d = posixpath.dirname(rel)
    joined = re.sub(r"\\\n", " ", text)
    for line in joined.splitlines():
        inc = re.match(r"^\s*-?(?:include|sinclude)\s+(.+)$", line)
        if inc:
            for f in inc.group(1).split():
                if "$" in f or "*" in f:
                    complete = False
                    continue
                sub = posixpath.normpath(posixpath.join(d, f)) if d else posixpath.normpath(f)
                t2, p2, c2 = make_targets(repo, sub, seen)
                targets |= t2
                patterns += p2
                complete = complete and c2
            continue
        m = MAKE_RULE.match(line)
        if not m:
            continue
        for t in m.group(1).split():
            if "$" in t:
                complete = False
            elif t == ".DEFAULT":
                patterns.append("*")   # the rule for every target that has no other rule
            elif "%" in t:
                patterns.append(t.replace("%", "*"))
            else:
                targets.add(t)
    return targets, patterns, complete


# --------------------------------------------------------------------------- versions

LANG_OF = {"node": "node", "nodejs": "node", "node.js": "node", "python": "python", "java": "java",
           "jdk": "java", "openjdk": "java", "go": "go", "golang": "go", "ruby": "ruby", "rust": "rust"}
PROSE_VERSION = re.compile(
    r"(?<![\w/.-])(node(?:\.?js)?|python|java|(?:open)?jdk|go(?:lang)?|ruby|rust)"
    r"(?:\s*(?:version|v(?=\d)|>=|≥|=)\s*|\s+)(v?\d+(?:\.\d+){0,2})(?!\w|\.\d)(\+?)", re.I)
NEED = re.compile(r"(requir|need|prerequisite|must|minimum|at least|or later|or higher|or newer|"
                  r"or above|\+|>=|≥|install|必要|以上|使用)", re.I)
NOT_NEED = re.compile(r"(not supported|unsupported|deprecat|dropp|no longer|end[- ]of[- ]life|\bEOL\b|"
                      r"removed|legacy|older than|below|until|was |were |previously|starting (?:from|with)|"
                      r"since|introduced|as of|built-in|builtin)", re.I)


def vkey(lang, s):
    s = s.lstrip("vV")
    nums = [int(x) for x in re.findall(r"\d+", s)[:3]]
    if not nums:
        return None
    if lang == "java":
        if nums[0] == 1 and len(nums) > 1:
            nums = nums[1:]
        return (nums[0],)
    if lang == "node":
        return (nums[0],)
    if len(nums) == 1:
        return (nums[0],) if lang != "go" and lang != "rust" else None
    return (nums[0], nums[1])


def vstr(k):
    return ".".join(str(x) for x in k)


def plausible(lang, k):
    if k is None:
        return False
    lo_hi = {"node": (4, 40), "java": (5, 40), "python": (2, 3), "go": (1, 1), "ruby": (1, 4),
             "rust": (1, 1)}[lang]
    if not (lo_hi[0] <= k[0] <= lo_hi[1]):
        return False
    if lang in ("go", "rust") and (len(k) < 2 or k[1] > 200):
        return False
    return True


def range_min(lang, spec):
    """The lowest version a range allows: '>=18.17 <21', '^3.10', '~=3.9', '18 || 20', '18.x'."""
    best = None
    for alt in re.split(r"\|\|", spec):
        m = re.search(r"(?:>=|\^|~=|~|==|=|>|≥)?\s*v?(\d+(?:\.(?:\d+|x|\*))*)", alt)
        if not m:
            continue
        k = vkey(lang, m.group(1).replace("x", "0").replace("*", "0"))
        if k is not None and (lang not in ("python", "go", "rust") or len(k) >= 2 or lang == "python"):
            if lang == "python" and len(k) == 1:
                k = (k[0], 0)
            best = k if best is None or k < best else best
    return best


def project_versions(repo, cwd=""):
    """{lang: [(key, file, kind)]} where kind is 'min' (a range's lower bound) or 'pin'."""
    out = {}

    def add(lang, k, f, kind):
        if k is not None and plausible(lang, k):
            out.setdefault(lang, []).append((k, f, kind))

    def rd(n):
        return repo.read(n)

    pkg = load_package(repo, "package.json") if repo.exists("package.json") else None
    if pkg:
        eng = pkg.get("engines")
        if isinstance(eng, dict) and isinstance(eng.get("node"), str):
            add("node", range_min("node", eng["node"]), "package.json engines.node", "min")
        vol = pkg.get("volta")
        if isinstance(vol, dict) and isinstance(vol.get("node"), str):
            add("node", vkey("node", vol["node"]), "package.json volta.node", "pin")
    for f in (".nvmrc", ".node-version"):
        t = rd(f)
        if t and re.match(r"^\s*v?\d", t):
            add("node", vkey("node", t.strip()), f, "pin")
    t = rd(".tool-versions")
    if t:
        for line in t.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                lang = {"nodejs": "node", "node": "node", "python": "python", "golang": "go",
                        "go": "go", "ruby": "ruby", "rust": "rust", "java": "java"}.get(parts[0])
                if lang:
                    v = re.sub(r"^[a-z]+-", "", parts[1])
                    add(lang, vkey(lang, v), ".tool-versions", "pin")
    t = rd(".python-version")
    if t and re.match(r"^\s*\d", t):
        add("python", vkey("python", t.split()[0]), ".python-version", "pin")
    t = rd("runtime.txt")
    if t:
        m = re.match(r"^\s*python-(\d+\.\d+)", t)
        if m:
            add("python", vkey("python", m.group(1)), "runtime.txt", "pin")
    t = rd("pyproject.toml")
    if t:
        m = re.search(r"^\s*requires-python\s*=\s*[\"']([^\"']+)", t, re.M)
        if m:
            add("python", range_min("python", m.group(1)), "pyproject.toml requires-python", "min")
        m = re.search(r"\[tool\.poetry\.dependencies\][^\[]*?^\s*python\s*=\s*[\"']([^\"']+)", t,
                      re.M | re.S)
        if m:
            add("python", range_min("python", m.group(1)), "pyproject.toml tool.poetry python", "min")
    for f in ("setup.py", "setup.cfg"):
        t = rd(f)
        if t:
            m = re.search(r"python_requires\s*[=:]\s*[\"']?([^\"'\n,)]+)", t)
            if m:
                add("python", range_min("python", m.group(1)), f + " python_requires", "min")
    t = rd("go.mod")
    if t:
        m = re.search(r"^go\s+(\d+\.\d+)", t, re.M)
        if m:
            add("go", vkey("go", m.group(1)), "go.mod go", "min")
    for f in ("build.gradle", "build.gradle.kts"):
        t = rd(f)
        if t:
            for pat in (r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)", r"jvmToolchain\(\s*(\d+)\s*\)",
                        r"(?:source|target)Compatibility\s*=?\s*(?:JavaVersion\.VERSION_)?['\"]?(\d+(?:[._]\d+)?)",
                        r"options\.release\.set\(\s*(\d+)\s*\)", r"release\s*=\s*(\d+)"):
                for m in re.finditer(pat, t):
                    add("java", vkey("java", m.group(1).replace("_", ".")), f, "min")
    t = rd("pom.xml")
    if t:
        for tag in ("maven.compiler.release", "maven.compiler.source", "java.version", "release"):
            m = re.search(r"<%s>\s*(\d+(?:\.\d+)?)\s*</%s>" % (re.escape(tag), re.escape(tag)), t)
            if m:
                add("java", vkey("java", m.group(1)), "pom.xml <%s>" % tag, "min")
                break
    t = rd(".java-version")
    if t and re.match(r"^\s*\d", t):
        add("java", vkey("java", t.strip()), ".java-version", "pin")
    t = rd(".sdkmanrc")
    if t:
        m = re.search(r"^java\s*=\s*(\d+(?:\.\d+)*)", t, re.M)
        if m:
            add("java", vkey("java", m.group(1)), ".sdkmanrc", "pin")
    t = rd(".ruby-version")
    if t and re.match(r"^\s*(ruby-)?\d", t):
        add("ruby", vkey("ruby", t.strip().replace("ruby-", "")), ".ruby-version", "pin")
    t = rd("Gemfile")
    if t:
        m = re.search(r"^\s*ruby\s+[\"']([^\"']+)[\"']", t, re.M)
        if m:
            add("ruby", range_min("ruby", m.group(1)), "Gemfile ruby", "min")
    t = rd("Cargo.toml")
    if t:
        m = re.search(r"^\s*rust-version\s*=\s*[\"'](\d+\.\d+)", t, re.M)
        if m:
            add("rust", vkey("rust", m.group(1)), "Cargo.toml rust-version", "min")
    for f in ("rust-toolchain", "rust-toolchain.toml"):
        t = rd(f)
        if t:
            # rust-toolchain.toml: channel = "1.90"; the old plain file: the channel alone
            m = (re.search(r"^\s*channel\s*=\s*[\"'](\d+\.\d+)", t, re.M) if f.endswith(".toml")
                 else re.match(r"^\s*(\d+\.\d+)", t))
            if m:
                add("rust", vkey("rust", m.group(1)), f, "pin")
    return out


def requirement(vers, lang):
    """(key, file, kind) the document is compared with: the strictest range bound, else the lowest pin."""
    items = vers.get(lang) or []
    mins = [x for x in items if x[2] == "min"]
    if mins:
        return max(mins, key=lambda x: x[0])
    pins = [x for x in items if x[2] == "pin"]
    if pins:
        return min(pins, key=lambda x: x[0])
    return None


COMMAND_VERSION = [
    (re.compile(r"^(?:nvm|fnm|n)\s+(?:install|use|i)\s+v?(\d+(?:\.\d+)*)\b"), "node"),
    (re.compile(r"^volta\s+(?:install|pin)\s+node@(\d+(?:\.\d+)*)"), "node"),
    (re.compile(r"^asdf\s+(?:install|local|global|set)\s+nodejs\s+(\d+(?:\.\d+)*)"), "node"),
    (re.compile(r"^brew\s+install\s+node@(\d+)"), "node"),
    (re.compile(r"^pyenv\s+(?:install|local|global|shell)\s+(\d+\.\d+(?:\.\d+)?)\b"), "python"),
    (re.compile(r"^(?:conda|mamba|micromamba)\s+create\b.*\bpython=(\d+\.\d+)"), "python"),
    (re.compile(r"^uv\s+(?:python\s+install|venv\b.*(?:--python|-p))\s+(\d+\.\d+)"), "python"),
    (re.compile(r"^brew\s+install\s+python@(\d+\.\d+)"), "python"),
    (re.compile(r"^asdf\s+(?:install|local|global|set)\s+python\s+(\d+\.\d+)"), "python"),
    (re.compile(r"^sdk\s+(?:install|use|default)\s+java\s+(\d+(?:\.\d+)*)"), "java"),
    (re.compile(r"^brew\s+install\s+openjdk@(\d+)"), "java"),
    (re.compile(r"^brew\s+install\s+go@(\d+\.\d+)"), "go"),
    (re.compile(r"^rustup\s+(?:toolchain\s+install|default|install)\s+(\d+\.\d+)"), "rust"),
    (re.compile(r"^rbenv\s+(?:install|local|global)\s+(\d+\.\d+(?:\.\d+)?)"), "ruby"),
]


# --------------------------------------------------------------------------- the checker

class DocState:
    def __init__(self):
        self.cwd = ""          # relative to the root; None = unknown; "\x00out" = outside, before a clone
        self.start = ""        # where the document's commands start
        self.clone = None
        self.created = set()   # paths made by earlier commands
        self.built = False     # an earlier command could have produced files
        self.configured = False  # cmake / configure / meson ran: a Makefile may have been written
        self.fetched = False   # an earlier command downloaded or unpacked something
        self.inline = False    # reading inline code in prose: the folder is a guess
        self.hints = []        # folders the prose just before the block names
        self.shown = None      # the language of the block just before, when it was not shell
        self.extracted = False  # an archive was unpacked: its files are not in the repository


def check_repo(repo, docs=None, explain=False):
    """Return (findings, stats). A finding is (doc, line, code, message)."""
    docs = find_docs(repo) if docs is None else docs
    ign = Ignore(repo)
    vers = project_versions(repo)
    findings = []
    stats = {"docs": 0, "commands": 0, "checked": 0, "skipped": 0, "ignored": 0}
    if explain:
        stats["trace"] = []
    for doc in docs:
        text = repo.read(doc)
        if text is None:
            continue
        stats["docs"] += 1
        check_doc(repo, doc, text, ign, vers, findings, stats)
    # the repository disagreeing with itself: a pinned version below a declared minimum
    for lang, items in sorted(vers.items()):
        mins = [x for x in items if x[2] == "min"]
        if not mins:
            continue
        top = max(mins, key=lambda x: x[0])
        for k, f, kind in items:
            if kind == "pin" and k < top[0]:
                findings.append((f.split()[0], 1, "PINS", "%s pins %s %s but %s requires %s"
                                 % (f, lang, vstr(k), top[1], vstr(top[0]))))
    return findings, stats


def check_doc(repo, doc, text, ign, vers, findings, stats):
    st = DocState()
    d = posixpath.dirname(doc)
    if d and (d not in DOC_DIRS or posixpath.basename(doc).lower().startswith("readme")):
        st.cwd = st.start = d     # a README inside a folder is read from that folder
    block, lang = [], None
    events = list(read_markdown(text))
    for kind, lg, lineno, line in events + [("end", None, 0, "")]:
        if kind == "code":
            block.append((lineno, line))
            continue
        if block:
            run_block(repo, doc, block, lang, st, ign, vers, findings, stats)
            block = []          # the folders the prose named stay until the next heading
            st.shown = None if (lang or "") in SHELL_LANGS else {"py": "python"}.get(lang, lang)
        if kind == "open":
            lang = lg
        elif kind == "heading":
            st.hints = []
            if st.cwd is None:
                st.cwd = st.start
        elif kind == "prose":
            prose_versions(doc, lineno, line, vers, findings)
            for m in INLINE.finditer(line):
                code = m.group(2).strip()
                # "from the `docs` directory", "the script `scripts/x/compare.sh`": a folder the
                # next block may be meant to run in
                if code and " " not in code and is_pathlike(code.strip("./") or "."):
                    rel = norm("", code.strip("/"))
                    if rel and repo.isdir(rel):
                        st.hints.append(rel)
                    elif rel and repo.exists(rel) and posixpath.dirname(rel):
                        st.hints.append(posixpath.dirname(rel))
                    elif rel and "/" in rel:
                        # `test/astro-basic.test.js` "in the package's directory": the folders it is in
                        for p in repo.ending(rel)[:3]:
                            st.hints.append(p[:-len(rel)].rstrip("/"))
                first = code.split()[0] if code.split() else ""
                # prose quotes commands for many reasons; only the ones that name a script or a
                # target are read there, not paths
                if first in ("npm", "pnpm", "yarn", "bun", "make"):
                    saved = st.cwd
                    st.inline = True
                    run_block(repo, doc, [(lineno, code)], "sh", st, ign, vers, findings, stats,
                              inline=True)
                    st.cwd, st.inline = saved, False


def prose_versions(doc, lineno, line, vers, findings):
    if not NEED.search(line) or NOT_NEED.search(line):
        return
    seen = set()
    for m in PROSE_VERSION.finditer(line):
        lang = LANG_OF.get(m.group(1).lower().replace("golang", "go"), None)
        if m.group(1).lower() in ("go", "golang"):
            lang = "go"
        if lang is None:
            continue
        k = vkey(lang, m.group(2))
        if lang == "python" and k is not None and len(k) == 1:
            k = (k[0], 0) if k[0] == 3 else k
        if not plausible(lang, k) or (lang, k) in seen:
            continue
        seen.add((lang, k))
        compare(doc, lineno, lang, k, "says", vers, findings)


def compare(doc, lineno, lang, k, verb, vers, findings):
    req = requirement(vers, lang)
    if req is None:
        return
    rk, rf, kind = req
    n = min(len(k), len(rk))
    if k[:n] < rk[:n]:
        code = "VERSION" if kind == "min" else "VERSION?"
        note = ""
        if lang == "go" and k >= (1, 21):
            code, note = "VERSION?", (" (go %s fetches the newer toolchain itself unless "
                                      "GOTOOLCHAIN=local)" % vstr(k))
        findings.append((doc, lineno, code, "the document %s %s %s; %s %s %s%s"
                         % (verb, lang, vstr(k), rf, "requires" if kind == "min" else "pins",
                            vstr(rk), note)))


def run_block(repo, doc, block, lang, st, ign, vers, findings, stats, inline=False):
    lang = (lang or "").lower()
    if lang not in SHELL_LANGS:
        return
    prompted = lang in PROMPTED_LANGS
    inherited = st.cwd      # the folder an earlier block left us in
    moved = False
    for lineno, line, had_prompt in logical_lines(block, prompted):
        cmds = split_commands(line)
        if cmds is None:
            stats["skipped"] += 1
            continue
        for toks in cmds:
            toks = strip_prefix(toks)
            if not toks:
                continue
            if (lang == "" or prompted) and not inline and not had_prompt and toks[0] not in TOOLS \
                    and not toks[0].startswith("./"):
                continue      # an unlabelled block: only lines that start like a command
            stats["commands"] += 1
            before = stats["checked"]
            if toks[0] in ("cd", "pushd", "git"):
                moved = True
            alts = []
            if not moved and st.cwd == inherited and inherited not in (None, "\x00out"):
                # a block does not say which folder it runs in: it may go on from where the last
                # block cd'd, start over where the document starts or at the root, or run in a
                # folder the prose just named. Report only what is wrong read every one of those ways.
                alts = [a for a in [st.start, ""] + st.hints if a != st.cwd]
                alts = sorted(set(alts), key=alts.index)
            if alts:
                wrong_everywhere = True
                for a in alts:
                    shadow = copy.deepcopy(st)
                    shadow.cwd = a
                    other = []
                    one_command(repo, doc, lineno, toks, shadow, ign, vers, other, dict(stats))
                    if not other:
                        wrong_everywhere = False
                        break
                n0 = len(findings)
                one_command(repo, doc, lineno, toks, st, ign, vers, findings, stats)
                if not wrong_everywhere:
                    del findings[n0:]
            else:
                one_command(repo, doc, lineno, toks, st, ign, vers, findings, stats)
            if "trace" in stats:
                where = {None: "?", "\x00out": "(outside, before cd into the clone)"}.get(st.cwd, st.cwd or ".")
                stats["trace"].append("%s:%d: [%s] %s  -> %d checked" % (
                    doc, lineno, where, " ".join(toks), stats["checked"] - before))


def strip_prefix(toks):
    i = 0
    while i < len(toks) and (toks[i] in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i])):
        i += 1
        if i < len(toks) and toks[i - 1] == "sudo":
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
    return toks[i:]


def report_path(repo, doc, lineno, st, ign, findings, stats, rel, what):
    """The command needs `rel`. Say so if it is missing and nothing explains that."""
    if rel is None:
        return
    stats["checked"] += 1
    if repo.exists(rel):
        return
    if st.start and rel.startswith(st.start + "/") and repo.exists(rel[len(st.start) + 1:]):
        return            # a folder's README written from the root after all
    for c in st.created:
        if rel == c or rel.startswith(c + "/"):
            return
    if "node_modules" in rel.split("/") or ign.ignored(rel) or st.extracted:
        stats["ignored"] += 1
        return
    code = "PATH?" if (st.built or st.fetched) else "PATH"
    why = "" if code == "PATH" else " (an earlier step may make it)"
    base = posixpath.basename(rel)
    elsewhere = repo.named(base) if "." in base else []
    if elsewhere:
        why += "; %s is at %s" % (base, ", ".join(elsewhere[:3]))
    findings.append((doc, lineno, code, "%s %s: not in the repository%s" % (what, rel, why)))


def one_command(repo, doc, lineno, toks, st, ign, vers, findings, stats):
    cmd, args = toks[0], toks[1:]
    joined = " ".join(toks)
    for rx, lang in COMMAND_VERSION:
        m = rx.match(joined)
        if m:
            k = vkey(lang, m.group(1))
            if lang == "python" and k is not None and len(k) == 1:
                k = None
            if plausible(lang, k):
                compare(doc, lineno, lang, k, "installs", vers, findings)
    if cmd == "git" and args[:1] == ["clone"]:
        pos, i = [], 1
        while i < len(args):
            if args[i] in CLONE_VALUE_OPTIONS:
                i += 2
                continue
            if not args[i].startswith("-"):
                pos.append(args[i])
            i += 1
        if pos:
            name = pos[1] if len(pos) > 1 else re.sub(r"\.git$", "", pos[0].rstrip("/").rsplit("/", 1)[-1])
            st.clone = name
            st.cwd = "\x00out"
        return
    if st.cwd == "\x00out":
        if cmd == "cd" and args:
            target = args[0].rstrip("/")
            unknown = not st.clone or PLACEHOLDER in st.clone     # git clone <this-repo>
            for name in (st.clone, repo.name) if not unknown else (target.split("/")[0],):
                if name and target == name:
                    st.cwd = ""
                    return
                if name and target.startswith(name + "/"):
                    st.cwd = norm("", target[len(name) + 1:])
                    return
        return
    if st.cwd is None:
        # lost track of the directory (cd to a variable, ~, a failed cd) until a cd that works
        # from where the document starts
        if cmd in ("cd", "pushd") and args and is_pathlike(args[0]):
            for base in (st.start, ""):
                alt = norm(base, args[0].rstrip("/") or ".")
                if alt is not None and repo.isdir(alt):
                    stats["checked"] += 1
                    st.cwd = alt
                    break
        return
    cwd = st.cwd

    if cmd in ("cd", "pushd"):
        if not args or args[0] in ("-", "~") or not is_pathlike(args[0]):
            st.cwd = None
            return
        target = args[0].rstrip("/") or "."
        for name in (repo.name, st.clone):
            # `cd fd/tests` in fd's own README: written from the folder the repository sits in
            if name and target.startswith(name + "/") and not repo.isdir(norm(cwd, target) or "\x00") \
                    and repo.isdir(target[len(name) + 1:]):
                stats["checked"] += 1
                st.cwd = target[len(name) + 1:]
                return
        if target == repo.name or target == st.clone:
            if not repo.isdir(norm(cwd, target) or "\x00"):
                st.cwd = ""
                return
        rel = norm(cwd, target)
        if rel is None:
            st.cwd = None
            return
        known = repo.isdir(rel) or any(rel == c or rel.startswith(c + "/") for c in st.created)
        if not known:
            # documents rarely say which folder a block starts in; a cd that works from where
            # the document starts is taken as written from there
            for base in (st.start, ""):
                alt = norm(base, target)
                if alt is not None and alt != rel and repo.isdir(alt):
                    stats["checked"] += 1
                    st.cwd = alt
                    return
            report_path(repo, doc, lineno, st, ign, findings, stats, rel, "cd")
            st.cwd = None
            return
        stats["checked"] += 1
        st.cwd = rel
        return

    if cmd in ("cp", "mv", "ln", "rsync"):
        pos = [a for a in args if not a.startswith("-")]
        if pos and PLACEHOLDER in pos[-1]:
            return        # `cp build/x.c <your-path-to-undici>/deps/`: run in another repository
        if len(pos) >= 2:
            for src in pos[:-1]:
                if cmd == "ln":
                    continue
                if is_pathlike(src):
                    report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, src), cmd)
            dst = pos[-1]
            if is_pathlike(dst):
                d = norm(cwd, dst)
                if d is not None:
                    st.created.add(d)
                    if repo.isdir(d):
                        for src in pos[:-1]:
                            n = norm(d, posixpath.basename(src.rstrip("/")))
                            if n:
                                st.created.add(n)
        return
    if cmd in ("mkdir", "touch"):
        for a in args:
            if not a.startswith("-") and is_pathlike(a):
                d = norm(cwd, a)
                if d is not None:
                    st.created.add(d)
        return
    if cmd == "git" and args[:2] == ["worktree", "add"]:
        pos = [a for a in args[2:] if not a.startswith("-")]
        if pos and is_pathlike(pos[0]):
            st.created.add(norm(cwd, pos[0]))
        return
    if cmd in ("curl", "wget", "tar", "unzip", "7z", "gh", "gsutil", "aws", "scp", "git"):
        st.fetched = True
        if cmd in ("tar", "unzip", "7z") and not any(a in ("-c", "-cf", "-czf", "c", "czf", "cf") for a in args):
            st.extracted = True
        for i, a in enumerate(args):
            if a in ("-o", "-O", "--output", "--output-document") and i + 1 < len(args):
                d = norm(cwd, args[i + 1]) if is_pathlike(args[i + 1]) else None
                if d:
                    st.created.add(d)
        return
    redirect_targets(toks, cwd, st)
    if cmd in ("cmake", "meson", "autoreconf", "qmake", "./configure", "./autogen.sh", "./bootstrap",
               "../configure", "perl") or cmd.endswith("/configure"):
        st.configured = True

    if cmd in ("source", "."):
        if args and is_pathlike(args[0]):
            report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, args[0]), cmd)
        return
    if cmd.startswith("./") or cmd.startswith(".\\") or ("/" in cmd and is_pathlike(cmd)):
        report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, cmd), "run")
        return
    if cmd in ("bash", "sh", "zsh", "pwsh", "powershell"):
        pos = [a for a in args if not a.startswith("-")]
        if "-c" in args or "-Command" in args or "-s" in args or not pos:
            return        # -s: the script comes from stdin (`curl ... | bash -s -- 0.8.3`)
        if is_pathlike(pos[0]) and ("/" in pos[0] or re.search(r"\.(sh|bash|zsh|ps1)$", pos[0])):
            report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, pos[0]), cmd)
        return
    if cmd in ("python", "python3", "py", "pypy3") or re.match(r"^python3\.\d+$", cmd):
        python_command(repo, doc, lineno, args, st, ign, findings, stats)
        return
    if cmd in ("pip", "pip3") or (cmd == "uv" and args[:1] == ["pip"]):
        pip_args = args[1:] if cmd == "uv" else args
        pip_command(repo, doc, lineno, pip_args, st, ign, findings, stats)
        return
    made = PROJECT_MAKERS.get((cmd, args[0] if args else None))
    if made is not None:
        # uv init NAME, cargo new NAME, django-admin startproject NAME, npm create vite NAME ...
        pos = [a for a in args[1:] if not a.startswith("-")][made:]
        if pos and is_pathlike(pos[0]):
            st.created.add(norm(cwd, pos[0]))
        st.fetched = True
        return
    if cmd == "uv" and args[:1] == ["venv"]:
        pos = [a for a in args[1:] if not a.startswith("-")]
        st.created.add(norm(cwd, pos[0]) if pos and is_pathlike(pos[0]) else norm(cwd, ".venv"))
        return
    if cmd in ("virtualenv",):
        pos = [a for a in args if not a.startswith("-")]
        if pos and is_pathlike(pos[0]):
            st.created.add(norm(cwd, pos[0]))
        return
    if cmd == "node":
        pos = [a for a in args if not a.startswith("-")]
        if pos and is_pathlike(pos[0]) and (re.search(r"\.(c|m)?js$|\.ts$", pos[0]) or "/" in pos[0]):
            rel = norm(cwd, pos[0])
            # node resolves x as x, x.js, x.json, x/index.js (and a package.json "main")
            if rel is not None and not re.search(r"\.(c|m)?js$|\.ts$", rel) and any(
                    repo.exists(rel + ext) for ext in (".js", ".cjs", ".mjs", ".json")):
                return
            report_path(repo, doc, lineno, st, ign, findings, stats, rel, "node")
        return
    if cmd in ("npm", "pnpm", "yarn", "bun"):
        js_command(repo, doc, lineno, cmd, args, st, ign, findings, stats)
        return
    if cmd == "make" or cmd == "gmake":
        make_command(repo, doc, lineno, args, st, ign, findings, stats)
        return
    if cmd in ("docker-compose",) or (cmd == "docker" and args[:1] == ["compose"]):
        compose_command(repo, doc, lineno, args[1:] if cmd == "docker" else args, st, ign, findings,
                        stats)
        return
    if cmd == "docker" and args[:1] in (["build"], ["buildx"]):
        for i, a in enumerate(args):
            if a in ("-f", "--file") and i + 1 < len(args) and is_pathlike(args[i + 1]):
                report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, args[i + 1]),
                            "docker build -f")
        return
    if cmd in ("conda", "mamba", "micromamba"):
        for i, a in enumerate(args):
            if a in ("-f", "--file") and i + 1 < len(args) and is_pathlike(args[i + 1]):
                report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, args[i + 1]),
                            cmd + " -f")
        return
    if BUILD_WORDS.search(" ".join(toks)):
        st.built = True


def redirect_targets(toks, cwd, st):
    for i, t in enumerate(toks):
        if t in (">", ">>") and i + 1 < len(toks) and is_pathlike(toks[i + 1]):
            d = norm(cwd, toks[i + 1])
            if d:
                st.created.add(d)


def python_command(repo, doc, lineno, args, st, ign, findings, stats):
    cwd = st.cwd
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-m" and i + 1 < len(args):
            mod = args[i + 1]
            rest = args[i + 2:]
            if mod == "pip":
                pip_command(repo, doc, lineno, rest, st, ign, findings, stats)
            elif mod in ("venv", "virtualenv"):
                pos = [x for x in rest if not x.startswith("-")]
                if pos and is_pathlike(pos[0]):
                    st.created.add(norm(cwd, pos[0]))
            elif BUILD_WORDS.search(" ".join(args)):
                st.built = True
            return
        if a in ("-c",):
            return
        if a.startswith("-"):
            i += 1
            continue
        if a.endswith(".py") and is_pathlike(a):
            if st.shown == "python" and "/" not in a:
                return    # the block just before it is the file: a tutorial the reader types in
            report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, a), "python")
        if BUILD_WORDS.search(" ".join(args)):
            st.built = True
        return


def pip_command(repo, doc, lineno, args, st, ign, findings, stats):
    cwd = st.cwd
    if not args or args[0] not in ("install", "download", "wheel", "sync", "compile"):
        return
    i = 1
    while i < len(args):
        a = args[i]
        if a in ("-r", "--requirement", "-c", "--constraint") and i + 1 < len(args):
            f = args[i + 1]
            if is_pathlike(f):
                report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, f), "pip " + a)
            i += 2
            continue
        m = re.match(r"^(?:-r|--requirement=)(.+)$", a)
        if m and is_pathlike(m.group(1)):
            report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, m.group(1)), "pip -r")
            i += 1
            continue
        if a in ("-e", "--editable") and i + 1 < len(args):
            a = args[i + 1]
            i += 1
        if not a.startswith("-"):
            p = re.sub(r"\[.*$", "", a)
            if (p.startswith(".") or p.endswith("/")) and is_pathlike(p):
                rel = norm(cwd, p)
                report_path(repo, doc, lineno, st, ign, findings, stats, rel, "pip install")
        i += 1
    st.built = True


def js_command(repo, doc, lineno, cmd, args, st, ign, findings, stats):
    cwd = st.cwd
    rest, name, kind = [], None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--prefix", "-C", "--dir", "--cwd") and i + 1 < len(args):
            if not is_pathlike(args[i + 1]):
                return
            d = norm(cwd, args[i + 1])
            if d is None:
                return
            cwd = d
            i += 2
            continue
        m = re.match(r"^--(?:prefix|dir|cwd)=(.+)$", a)
        if m:
            d = norm(cwd, m.group(1)) if is_pathlike(m.group(1)) else None
            if d is None:
                return
            cwd = d
            i += 1
            continue
        if a in ("-w", "--workspace", "--filter", "-F", "--recursive", "-r", "-ws", "--workspaces") \
                or a.startswith("--workspace=") or a.startswith("--filter=") or a == "workspace":
            return        # the script lives in another package; not followed
        rest.append(a)
        i += 1
    if not rest:
        if cmd in ("yarn", "pnpm", "bun"):
            st.built = True
        return
    sub = rest[0]
    if cmd == "npm":
        if sub in ("run", "run-script", "rum", "urn"):
            name, kind = next((x for x in rest[1:] if not x.startswith("-")), None), "run"
            if "--if-present" in rest:
                return
        elif sub in NPM_LIFECYCLE:
            name, kind = NPM_LIFECYCLE[sub], "lifecycle"
        else:
            if sub in ("install", "i", "ci", "add"):
                st.built = True
            return
    elif cmd == "pnpm":
        if sub == "run":
            name, kind = next((x for x in rest[1:] if not x.startswith("-")), None), "run"
        elif sub in ("test", "t", "start"):
            name, kind = {"t": "test"}.get(sub, sub), "lifecycle"
        elif sub in PNPM_BUILTINS or sub.startswith("-"):
            if sub in ("install", "i", "add"):
                st.built = True
            return
        else:
            name, kind = sub, "fallback"
    elif cmd == "yarn":
        if sub == "run":
            name, kind = next((x for x in rest[1:] if not x.startswith("-")), None), "fallback"
        elif sub in YARN_BUILTINS or sub.startswith("-"):
            if sub in ("install", "add"):
                st.built = True
            return
        elif sub in ("test", "start"):
            name, kind = sub, "fallback"
        else:
            name, kind = sub, "fallback"
    elif cmd == "bun":
        if sub.startswith("-"):
            return
        if sub == "run":
            name, kind = next((x for x in rest[1:] if not x.startswith("-")), None), "fallback"
        elif sub in ("test", "install", "i", "add", "x", "create", "init", "build", "upgrade", "pm",
                     "link", "unlink", "remove", "rm", "update", "outdated", "publish", "patch"):
            if sub in ("install", "i", "add", "build"):
                st.built = True
            return
        else:
            name, kind = sub, "fallback"
    if not name or PLACEHOLDER in name or not re.match(r"^[\w:.@/+-]+$", name):
        return
    if name.startswith("./") or name.endswith((".js", ".ts", ".mjs", ".cjs")):
        return             # bun/yarn running a file
    stats["checked"] += 1
    pkg_rel = nearest(repo, cwd, ["package.json"])
    if BUILD_WORDS.search(name):
        st.built = True
    if st.inline:
        # prose does not say which package it means: any package.json that has the script will do
        for other in repo.named("package.json"):
            o = load_package(repo, other)
            if o and isinstance(o.get("scripts"), dict) and name in o["scripts"]:
                return
        if pkg_rel is None and repo.named("package.json"):
            return
    if pkg_rel is None:
        if kind in ("run", "lifecycle") and not st.inline:
            findings.append((doc, lineno, "NOPROJ", "%s %s: no package.json in %s or above"
                             % (cmd, " ".join(rest[:2]), cwd or "the root")))
        return
    pkg = load_package(repo, pkg_rel)
    if pkg is None:
        return
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    if name in scripts:
        return
    if kind == "lifecycle":
        if name in ("stop",):
            return
        if name in ("start", "restart"):
            if repo.exists(norm(posixpath.dirname(pkg_rel), "server.js") or "server.js"):
                return
    # a workspace root: the document may mean a package of the workspace
    workspace = bool(pkg.get("workspaces")) or repo.exists(
        norm(posixpath.dirname(pkg_rel), "pnpm-workspace.yaml") or "pnpm-workspace.yaml")
    elsewhere = []
    if workspace:
        for other in repo.named("package.json"):
            o = load_package(repo, other) if other != pkg_rel else None
            if o and isinstance(o.get("scripts"), dict) and name in o["scripts"]:
                elsewhere.append(other)
    if cmd == "yarn" and ":" in name and elsewhere:
        return             # Yarn runs a script with a colon from any workspace that defines it
    if kind == "fallback":
        if st.inline:
            return         # prose: yarn/pnpm plugins and binaries are too many to know
        if name in dep_names(pkg) or name in ("tsc", "eslint", "prettier", "jest", "vitest", "vite",
                                              "next", "tsx", "ts-node", "webpack", "rollup",
                                              "esbuild", "playwright", "cypress", "mocha", "turbo",
                                              "nx", "lerna", "changeset", "husky", "node-gyp"):
            return
        findings.append((doc, lineno, "SCRIPT?", "%s %s: no script %r in %s (%s would try a binary of that "
                         "name next)" % (cmd, " ".join(rest[:2]), name, pkg_rel, cmd)))
        return
    near = close_names(name, scripts, ":")
    hint = ("; it has " + ", ".join(near)) if near else ""
    if elsewhere:
        # `pnpm test` "in the directory of the package you changed"
        findings.append((doc, lineno, "SCRIPT?", "%s %s: no script %r in the workspace root %s; "
                         "%d workspace package(s) have it, e.g. %s" % (
                             cmd, " ".join(rest[:2]), name, pkg_rel, len(elsewhere), elsewhere[0])))
        return
    findings.append((doc, lineno, "SCRIPT", "%s %s: no script %r in %s%s"
                     % (cmd, " ".join(rest[:2]), name, pkg_rel, hint)))


def close_names(name, names, sep):
    """Up to four names the document may have meant: same first part, or spelled alike."""
    names = sorted(set(names))
    same = [n for n in names if n.split(sep)[0] == name.split(sep)[0]]
    alike = difflib.get_close_matches(name, names, n=4, cutoff=0.6)
    out = []
    for n in alike + same:
        if n not in out:
            out.append(n)
    return out[:4]


def make_command(repo, doc, lineno, args, st, ign, findings, stats):
    cwd, mfile = st.cwd, None
    targets = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-C", "--directory") and i + 1 < len(args):
            d = norm(cwd, args[i + 1]) if is_pathlike(args[i + 1]) else None
            if d is None:
                return
            cwd = d
            i += 2
            continue
        if a in ("-f", "--file", "--makefile") and i + 1 < len(args):
            mfile = args[i + 1]
            i += 2
            continue
        m = re.match(r"^(?:-C|--directory=)(.+)$", a)
        if m:
            d = norm(cwd, m.group(1)) if is_pathlike(m.group(1)) else None
            if d is None:
                return
            cwd = d
            i += 1
            continue
        if a in ("-j", "--jobs", "-l", "-o", "-W") and i + 1 < len(args) and re.match(r"^\d", args[i + 1]):
            i += 2
            continue
        if a.startswith("-") or "=" in a:
            i += 1
            continue
        targets.append(a)
        i += 1
    if any(t in ("/", "|", "or", "...", "…") for t in targets):
        return            # `make logs / ps` is shorthand for several commands, not one
    make_rule_check(repo, doc, lineno, cwd, mfile, targets, st, ign, findings, stats)
    st.built = True


def make_rule_check(repo, doc, lineno, cwd, mfile, targets, st, ign, findings, stats):
    if mfile:
        if not is_pathlike(mfile):
            return
        rel = norm(cwd, mfile)
        if rel is None or not repo.exists(rel):
            report_path(repo, doc, lineno, st, ign, findings, stats, rel, "make -f")
            return
    else:
        rel = next(((cwd + "/" if cwd else "") + n for n in MAKEFILES
                    if repo.exists((cwd + "/" if cwd else "") + n)), None)
        if rel is None:
            stats["checked"] += 1
            if st.configured or st.fetched or any(c == cwd for c in st.created) or \
                    any(nearest(repo, cwd, [n]) for n in GENERATES_MAKEFILE):
                return     # the Makefile is generated (cmake, configure) or came with a download
            if st.inline:
                return     # prose mentions `make` for other projects too
            findings.append((doc, lineno, "NOPROJ", "make %s: no Makefile in %s"
                             % (" ".join(targets), cwd or "the root")))
            return
    have, patterns, complete = make_targets(repo, rel)
    for t in targets:
        if not re.match(r"^[\w./-]+$", t) or PLACEHOLDER in t:
            continue
        stats["checked"] += 1
        if t in have or any(fnmatch.fnmatch(t, p) for p in patterns):
            continue
        if repo.exists(norm(posixpath.dirname(rel), t) or t):
            continue       # a file that exists: make says it is up to date
        code = "TARGET" if complete else "TARGET?"
        near = close_names(t, [x for x in have if not x.startswith(".")], "-")
        hint = ("; it has " + ", ".join(near)) if near else ""
        why = "" if complete else " (the Makefile includes files that could not be read)"
        findings.append((doc, lineno, code, "make %s: no rule for %r in %s%s%s" % (t, t, rel, hint, why)))


def compose_command(repo, doc, lineno, args, st, ign, findings, stats):
    cwd = st.cwd
    files = []
    for i, a in enumerate(args):
        if a in ("-f", "--file") and i + 1 < len(args):
            files.append(args[i + 1])
        elif a.startswith("--file="):
            files.append(a.split("=", 1)[1])
        elif a in ("--project-directory",) and i + 1 < len(args):
            d = norm(cwd, args[i + 1]) if is_pathlike(args[i + 1]) else None
            if d is None:
                return
            cwd = d
    if files:
        for f in files:
            if is_pathlike(f):
                report_path(repo, doc, lineno, st, ign, findings, stats, norm(cwd, f), "docker compose -f")
        return
    if not args or args[0] in ("version", "ls", "--help", "help"):
        return
    stats["checked"] += 1
    if nearest(repo, cwd, COMPOSE_FILES) is None:
        findings.append((doc, lineno, "NOPROJ", "docker compose %s: no compose file in %s or above"
                         % (args[0], cwd or "the root")))


# --------------------------------------------------------------------------- output

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--doc", action="append", help="a document to read (repeatable); default: README* etc.")
    ap.add_argument("--tsv", action="store_true")
    ap.add_argument("--strict", action="store_true", help="warnings fail too")
    ap.add_argument("--explain", action="store_true",
                    help="also print every command read, the folder it was read in, and how many "
                         "things it checked")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    repo = LocalRepo(a.root)
    docs = [d.replace("\\", "/") for d in a.doc] if a.doc else None
    if docs:
        docs = [os.path.relpath(os.path.abspath(d), repo.root).replace("\\", "/")
                if os.path.isabs(d) or os.path.exists(d) and not repo.exists(d) else d for d in docs]
    findings, stats = check_repo(repo, docs, explain=a.explain)
    for line in stats.get("trace", []):
        print("read " + line)
    if stats["docs"] == 0:
        print("no document to read in %s (looked for README*, CONTRIBUTING*, docs/*setup* ...)" % repo.root)
        return 2
    errors = warnings = 0
    for doc, line, code, msg in findings:
        lv = LEVEL[code]
        errors += lv == "error"
        warnings += lv == "warning"
        if a.tsv:
            print("\t".join((doc, str(line), lv, code, msg)))
        else:
            print("%s:%d: %s %s %s" % (doc, line, lv, code, msg))
    print("%d documents, %d commands read, %d things checked against the repository, %d lines not "
          "read (substitutions, heredocs), %d paths skipped as ignored or generated; %d errors, "
          "%d warnings" % (stats["docs"], stats["commands"], stats["checked"], stats["skipped"],
                           stats["ignored"], errors, warnings), file=sys.stderr)
    if stats["checked"] == 0:
        print("nothing was checked: no command in these documents touches the repository",
              file=sys.stderr)
    return 1 if errors or (a.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
