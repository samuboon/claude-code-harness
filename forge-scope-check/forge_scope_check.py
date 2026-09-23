# -*- coding: utf-8 -*-
"""forge-scope-check: do the scopes in a Forge app's manifest.yml open the Jira REST
calls its code makes?

    python forge_scope_check.py path/to/forge-app            # human-readable report
    python forge_scope_check.py path/to/forge-app --tsv      # one row per call / finding
    python forge_scope_check.py app --allow-deprecated       # deprecated calls warn instead of fail

Reads `manifest.yml` and every .js/.jsx/.ts/.tsx/.mjs/.cjs file under `src/` (or the app
folder, minus node_modules, if there is no src/). Finds each `requestJira(route`...`)`,
reads the HTTP method from the options literal right after it, looks the call up in
jira_scopes.json (built from Atlassian's published OpenAPI definitions by build_table.py),
and checks that the declared scopes satisfy it: all of the classic scopes, or all of the
granular ones. Jira Software (`/rest/agile/`, `/rest/software/`) has no classic scopes.

Exit codes:
    0  every call was resolved and nothing is wrong
    1  at least one finding (missing scope, asUser() outside UI, deprecated call)
    2  the app could not be read (no manifest.yml, YAML this reader does not handle)
    3  no findings, but some calls could not be checked -- not a pass

Standard library only. No npm, no Forge CLI, no network.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE = HERE / "jira_scopes.json"
CODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "out", "coverage"}
SOFTWARE_PREFIXES = ("/rest/agile/", "/rest/software/")

# Scopes that no Jira REST call asks for but that a Forge app legitimately declares for
# something else (storage, product events, its own app system token, egress...). They are
# never reported as unused.
NOT_FROM_REST = {
    "storage:app",
    "read:app-system-token",
    "read:app-user-token",
    "report:personal-data",
}


# --------------------------------------------------------------------------- #
# A small YAML reader: block mappings and sequences, scalars, flow lists       #
# ([a, b]) and block strings (| and >). Anything else raises YamlError, which  #
# the tool reports as exit 2 rather than guessing.                             #
# --------------------------------------------------------------------------- #

class YamlError(Exception):
    pass


def _strip_comment(s):
    out, quote = [], None
    for c in s:
        if quote:
            out.append(c)
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
            out.append(c)
        elif c == "#" and (not out or out[-1] in " \t"):
            break
        else:
            out.append(c)
    return "".join(out).rstrip()


def _split_kv(text):
    """(key, rest) if the line is a mapping entry. The separator is a colon followed by
    a space or end of line -- `jira:jqlFunction:` must split at the last colon, and
    `storage:app` is not a mapping entry at all."""
    quote = None
    for i, c in enumerate(text):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
            return text[:i].strip().strip("\"'"), text[i + 1:].strip()
    return None


def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    if s.startswith("{") or s.startswith("&") or s.startswith("*") or s.startswith("!"):
        raise YamlError("flow mappings, anchors, aliases and tags are not supported: " + s)
    if s == "true":
        return True
    if s == "false":
        return False
    if s in ("null", "~", ""):
        return None
    try:
        return int(s)
    except ValueError:
        return s


def _lines(text):
    out = []
    raw = text.splitlines()
    i = 0
    while i < len(raw):
        s = _strip_comment(raw[i])
        i += 1
        if not s.strip():
            continue
        ind = len(s) - len(s.lstrip(" "))
        body = s.strip()
        pair = _split_kv(body[2:] if body.startswith("- ") else body)
        if pair and pair[1] in ("|", ">", "|-", ">-", "|+", ">+"):
            # block string: swallow every deeper-indented (or blank) line
            parts = []
            while i < len(raw) and (not raw[i].strip() or len(raw[i]) - len(raw[i].lstrip(" ")) > ind):
                parts.append(raw[i].strip())
                i += 1
            body = body[: len(body) - len(pair[1])] + '"' + " ".join(p for p in parts if p).replace('"', "'") + '"'
        out.append((ind, body))
    return out


def _parse(lines, i, indent):
    if i >= len(lines):
        return None, i
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _parse_seq(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines, i, indent):
    out = {}
    while i < len(lines):
        ind, text = lines[i]
        if ind < indent or text.startswith("- "):
            break
        if ind > indent:
            raise YamlError("unexpected indentation: " + text)
        pair = _split_kv(text)
        if pair is None:
            raise YamlError("not a mapping entry: " + text)
        key, rest = pair
        i += 1
        if rest:
            out[key] = _scalar(rest)
        elif i < len(lines) and lines[i][0] > indent:
            out[key], i = _parse(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            out[key], i = _parse_seq(lines, i, indent)
        else:
            out[key] = None
    return out, i


def _parse_seq(lines, i, indent):
    out = []
    while i < len(lines):
        ind, text = lines[i]
        if ind != indent or not text.startswith("- "):
            break
        item = text[2:].lstrip(" ")
        key_indent = indent + (len(text) - len(item))
        if _split_kv(item) is not None:
            sub = [(key_indent, item)]
            i += 1
            while i < len(lines) and lines[i][0] >= key_indent:
                sub.append(lines[i])
                i += 1
            value, used = _parse_map(sub, 0, key_indent)
            if used != len(sub):
                raise YamlError("could not read the item starting: " + text)
            out.append(value)
        else:
            out.append(_scalar(item))
            i += 1
    return out, i


def load_yaml(text):
    lines = _lines(text)
    if not lines:
        return {}
    value, i = _parse(lines, 0, lines[0][0])
    if i != len(lines):
        raise YamlError("stopped at line %d of %d: %s" % (i + 1, len(lines), lines[i][1]))
    return value


# --------------------------------------------------------------------------- #
# Reading the code                                                             #
# --------------------------------------------------------------------------- #

def strip_js_comments(text):
    """Blank out // and /* */ comments, leaving strings and templates alone. Keeps the
    length, so positions (line numbers) stay right."""
    out = list(text)
    i, n, quote = 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


ROUTE_RE = re.compile(r"\broute\s*`([^`]*)`")
# requestJira( / requestJira<T>( immediately before the route literal
CALL_BEFORE_RE = re.compile(r"\.\s*(request(?:Jira|Confluence|Bitbucket))\s*(?:<[^()]*>)?\s*\(\s*$")
CALL_RE = re.compile(r"\.\s*(request(?:Jira|Confluence|Bitbucket))\s*(?:<[^()]*>)?\s*\(\s*")
ASUSER_RE = re.compile(r"\basUser\s*\(\s*\)")


def normalize_path(raw):
    """`/rest/api/3/issue/${key}?fields=x` -> `/rest/api/3/issue/{}`."""
    body = raw.strip().split("?", 1)[0].split("#", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", body)
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def options_after(text, pos):
    """The object literal passed as the second argument, if the call has one right
    after position `pos`. Returns (kind, text): kind is "none", "literal" or "other"."""
    n = len(text)
    i = pos
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n or text[i] == ")":
        return "none", ""
    if text[i] != ",":
        return "other", ""
    i += 1
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i < n and text[i] == ")":
        return "none", ""
    ident = re.match(r"([A-Za-z_$][\w$]*)\s*\)", text[i:i + 80])
    if ident:
        return "ident", ident.group(1)
    if i >= n or text[i] != "{":
        return "other", ""
    start, depth, quote = i, 0, None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return "literal", text[start:i + 1]
        i += 1
    return "other", ""


def method_of(text, pos):
    """HTTP method of the call whose route literal ends at `pos`, or None if the
    options are not a literal we can read."""
    kind, opts = options_after(text, pos)
    if kind == "none":
        return "GET"
    if kind == "ident":
        # `requestJira(route`...`, JSON_HEADERS)`: read the constant if this file defines it
        d = re.search(r"\b(?:const|let|var)\s+" + re.escape(opts) + r"\s*=\s*(?=\{)", text)
        if not d:
            return None
        kind, opts = options_after(text[:d.end() - 1] + "," + text[d.end():], d.end() - 1)
        if kind != "literal":
            return None
    if kind == "other":
        return None
    m = re.search(r"\bmethod\s*:\s*(['\"`])(\w+)\1", opts)
    if m:
        return m.group(2).upper()
    if re.search(r"\bmethod\s*[:,}]", opts):
        return None  # method: someVariable / shorthand { method }
    return "GET"


def code_files(app):
    root = app / "src" if (app / "src").is_dir() else app
    out = []
    for p in sorted(root.rglob("*")):
        if p.suffix in CODE_EXT and p.is_file() and not (set(p.relative_to(app).parts) & SKIP_DIRS):
            out.append(p)
    return out


WRAP_DEF_RES = (
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
               r"(?:\(\s*([A-Za-z_$][\w$]*)[^()]*\)|([A-Za-z_$][\w$]*))\s*=>"),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(\s*([A-Za-z_$][\w$]*)()"),
)
ARG_IDENT_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*[,)]")


def wrapper_at(text, call):
    """If the request call at `call` (a CALL_RE match) passes straight through the first
    parameter of the function it sits in -- `const get = (path) => api.asApp().requestJira(path, OPTS)`
    -- return (wrapper name, method or None). Otherwise None."""
    arg = ARG_IDENT_RE.match(text, call.end())
    if not arg:
        return None
    before = text[max(0, call.start() - 400):call.start()]
    last = None
    for rx in WRAP_DEF_RES:
        for m in rx.finditer(before):
            if last is None or m.start() > last.start():
                last = m
    if last is None or arg.group(1) not in (last.group(2), last.group(3)):
        return None
    return last.group(1), method_of(text, arg.end() - 1)


def find_wrappers(texts):
    """{name: method or None} over every file. A name defined with two different methods
    gets None (unknown)."""
    out = {}
    for text in texts.values():
        for call in CALL_RE.finditer(text):
            if call.group(1) != "requestJira":
                continue
            w = wrapper_at(text, call)
            if w:
                name, meth = w
                out[name] = meth if out.get(name, meth) == meth else None
    return out


def calls_in(app, rel, text, wrappers=None):
    """[(product, method or None, path, line, how)] for every route literal in one file.
    `how` is "call" when the literal sits directly in requestJira(...) or in a known
    wrapper of it, "detached" when it is built apart from any call we can read, and
    "variable" for a request call whose path is not a route literal."""
    wrappers = wrappers or {}
    out = []
    for m in ROUTE_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        before = text[max(0, m.start() - 200):m.start()]
        call = CALL_BEFORE_RE.search(before)
        path = normalize_path(m.group(1))
        if call:
            out.append((call.group(1), method_of(text, m.end()), path, line, "call"))
            continue
        wrap = re.search(r"\b([A-Za-z_$][\w$]*)\s*\(\s*$", before)
        if wrap and wrap.group(1) in wrappers:
            out.append(("requestJira", wrappers[wrap.group(1)], path, line, "call"))
        else:
            out.append((None, None, path, line, "detached"))
    # request calls whose first argument is not a route literal (wrappers excepted)
    for m in CALL_RE.finditer(text):
        if text.startswith("route", m.end()):
            continue
        if m.group(1) == "requestJira" and wrapper_at(text, m):
            continue
        line = text.count("\n", 0, m.start()) + 1
        out.append((m.group(1), None, None, line, "variable"))
    return out


# --------------------------------------------------------------------------- #
# Matching a call against the table                                           #
# --------------------------------------------------------------------------- #

def load_table(path=TABLE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ops = data["operations"]
    index = {}
    for key in ops:
        meth, p = key.split(" ", 1)
        index.setdefault((meth, len(p.split("/"))), []).append(key)
    return data, ops, index


def resolve(method, path, ops, index):
    """Return (key, note) or (None, reason)."""
    note = ""
    if path.startswith("/rest/api/2/") or path.startswith("/rest/api/latest/"):
        path = "/rest/api/3/" + path.split("/", 4)[4]
        note = "v2/latest path checked against the v3 definition"
    key = method + " " + path
    if key in ops:
        return key, note
    segs = path.split("/")
    best, best_score = [], -1
    for cand in index.get((method, len(segs)), []):
        csegs = cand.split(" ", 1)[1].split("/")
        score, ok = 0, True
        for a, b in zip(segs, csegs):
            if a == b:
                score += a != "{}"
            elif b == "{}" and "{}" not in a:
                continue          # a literal id in the code, a parameter in the definition
            else:
                ok = False
                break
        if ok:
            if score > best_score:
                best, best_score = [cand], score
            elif score == best_score:
                best.append(cand)
    if len(best) == 1:
        return best[0], (note + "; " if note else "") + "literal segment matched a parameter"
    if len(best) > 1:
        return None, "ambiguous: " + " / ".join(sorted(best))
    return None, "not in the Jira platform or Jira Software definition"


# --------------------------------------------------------------------------- #
# Modules and asUser()                                                         #
# --------------------------------------------------------------------------- #

def function_refs(value, under_resolver=False, out=None):
    """[(function key, reached from a UI resolver?)] anywhere under one module entry."""
    out = [] if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "function" and isinstance(v, str):
                out.append((v, under_resolver))
            else:
                function_refs(v, under_resolver or k == "resolver", out)
    elif isinstance(value, list):
        for v in value:
            function_refs(v, under_resolver, out)
    return out


def handler_files(app, handler):
    """`index.run` -> src/index.js (or .ts, .jsx ...). Returns the existing ones."""
    mod = handler.rsplit(".", 1)[0] if "." in handler else handler
    base = app / "src" / mod
    found = [base.with_name(base.name + ext) for ext in CODE_EXT]
    found += [base / ("index" + ext) for ext in CODE_EXT]
    return [p for p in found if p.is_file()]


def asuser_findings(app, manifest, texts):
    """Handlers reached only from modules without a UI (jqlFunction, trigger,
    scheduledTrigger, webtrigger...) that call api.asUser() with no account id."""
    modules = manifest.get("modules") or {}
    if not isinstance(modules, dict):
        return [], 0
    handlers = {}
    for entry in modules.get("function") or []:
        if isinstance(entry, dict) and entry.get("key") and entry.get("handler"):
            handlers[entry["key"]] = str(entry["handler"])
    reach = {}
    for mod_name, entries in modules.items():
        if mod_name == "function" or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for fn, ui in function_refs(entry):
                reach.setdefault(fn, set()).add((mod_name, ui))
    out = []
    for fn, uses in sorted(reach.items()):
        if any(ui for _m, ui in uses) or fn not in handlers:
            continue
        mods = sorted({m for m, _ui in uses})
        for path in handler_files(app, handlers[fn]):
            text = texts.get(path)
            if text is None:
                continue
            for m in ASUSER_RE.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                out.append((path, line, fn, mods))
    # Files that also serve a UI-reached function: the call may belong to that one, so
    # the caller downgrades those to a warning instead of guessing.
    ui_files = set()
    for fn, uses in reach.items():
        if any(ui for _m, ui in uses) and fn in handlers:
            ui_files.update(handler_files(app, handlers[fn]))
    grouped = {}
    for path, line, fn, mods in out:
        g = grouped.setdefault((path, line), [set(), set()])
        g[0].add(fn)
        g[1].update(mods)
    merged = [(path, line, sorted(g[0]), sorted(g[1]), path in ui_files)
              for (path, line), g in sorted(grouped.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))]
    return merged, len(reach)


# --------------------------------------------------------------------------- #
# The check                                                                    #
# --------------------------------------------------------------------------- #

def check(app, ops, index, allow_deprecated=False):
    """Returns a dict with calls, findings, warnings, unchecked, declared, and error."""
    app = Path(app)
    res = {"app": app.name, "calls": [], "findings": [], "warnings": [], "unchecked": [],
           "declared": [], "error": None}
    mf = app / "manifest.yml"
    if not mf.is_file():
        res["error"] = "no manifest.yml in %s" % app
        return res
    try:
        manifest = load_yaml(mf.read_text(encoding="utf-8"))
    except (YamlError, UnicodeDecodeError) as e:
        res["error"] = "manifest.yml: %s" % e
        return res
    if not isinstance(manifest, dict):
        res["error"] = "manifest.yml is not a mapping"
        return res
    scopes = ((manifest.get("permissions") or {}).get("scopes")) or []
    if not isinstance(scopes, list):
        res["error"] = "permissions.scopes is not a list"
        return res
    declared = {s for s in scopes if isinstance(s, str)}
    res["declared"] = sorted(declared)

    files = code_files(app)
    if not files:
        res["error"] = "no code files under %s" % (app / "src")
        return res
    texts = {p: strip_js_comments(p.read_text(encoding="utf-8", errors="replace")) for p in files}

    wrappers = find_wrappers(texts)
    needed = {}          # scope -> keys that justify it
    for path, text in texts.items():
        rel = path.relative_to(app).as_posix()
        for product, method, p, line, how in calls_in(app, rel, text, wrappers):
            where = "%s:%d" % (rel, line)
            if how == "variable":
                res["unchecked"].append((where, product, "the path is not a route`...` literal at the call"))
                continue
            if how == "detached":
                res["unchecked"].append((where, p, "route`...` built apart from the request call; method unknown"))
                continue
            if product != "requestJira":
                res["unchecked"].append((where, p, "%s is not covered (Jira only)" % product))
                continue
            if method is None:
                res["unchecked"].append((where, p, "method is not a literal in the options"))
                continue
            key, note = resolve(method, p, ops, index)
            if key is None:
                res["unchecked"].append((where, method + " " + p, note))
                continue
            row = ops[key]
            res["calls"].append((where, key, note))
            classic, granular = set(row["classic"]), set(row["granular"])
            for s in classic | granular:
                needed.setdefault(s, set()).add(key)
            if row["deprecated"]:
                msg = "%s is marked deprecated in the definition" % key
                (res["warnings"] if allow_deprecated else res["findings"]).append(("DEPRECATED", where, msg))
            if not classic and not granular:
                continue
            ok_c = bool(classic) and classic <= declared
            ok_g = bool(granular) and granular <= declared
            if ok_c or ok_g:
                continue
            if key.split(" ", 1)[1].startswith(SOFTWARE_PREFIXES) or not classic:
                lack = sorted(granular - declared)
                extra = ""
                if declared & {"read:jira-work", "write:jira-work", "manage:jira-configuration",
                               "manage:jira-project", "read:jira-user"} and key.split(" ", 1)[1].startswith(SOFTWARE_PREFIXES):
                    extra = " (Jira Software has no classic scopes; read:jira-work does not open it)"
                res["findings"].append(("MISSING", where, "%s needs granular %s%s" % (key, ", ".join(lack), extra)))
            elif not granular:
                res["findings"].append(("MISSING", where, "%s needs %s" % (key, ", ".join(sorted(classic - declared)))))
            else:
                res["findings"].append(("MISSING", where, "%s needs classic %s, or granular %s" % (
                    key, ", ".join(sorted(classic - declared)), ", ".join(sorted(granular - declared)))))

    for path, line, fns, mods, shared in asuser_findings(app, manifest, texts)[0]:
        where = "%s:%d" % (path.relative_to(app).as_posix(), line)
        if shared:
            res["warnings"].append(("ASUSER", where,
                                    "api.asUser() in a file that serves both %s (no UI) and a UI resolver; "
                                    "check it is not reached from %s" % (", ".join(fns), ", ".join(mods))))
        else:
            res["findings"].append(("ASUSER", where,
                                    "api.asUser() in the handler of %s, reached only from %s "
                                    "(asUser() with no account id needs a UI module)"
                                    % (", ".join(fns), ", ".join(mods))))

    # Warnings: scopes nothing asks for, and classic scopes made redundant by granular ones.
    if not res["unchecked"]:
        for s in sorted(declared - set(needed) - NOT_FROM_REST):
            res["warnings"].append(("UNUSED", "manifest.yml",
                                    "%s is declared but no REST call found needs it "
                                    "(product events and other non-REST uses are not seen)" % s))
    called = {k for _w, k, _n in res["calls"]}
    for s in sorted(declared):
        keys = [k for k in called if s in ops[k]["classic"]]
        if keys and all(ops[k]["granular"] and set(ops[k]["granular"]) <= declared for k in keys):
            res["warnings"].append(("REDUNDANT", "manifest.yml",
                                    "%s is only needed by calls the declared granular scopes already open" % s))
    return res


def exit_code(res):
    if res["error"]:
        return 2
    if res["findings"]:
        return 1
    if res["unchecked"]:
        return 3
    return 0


def report(res, data, tsv=False):
    lines = []
    if tsv:
        lines.append("kind\twhere\tdetail")
        for w, k, n in res["calls"]:
            lines.append("CALL\t%s\t%s%s" % (w, k, (" (" + n + ")") if n else ""))
        for kind, w, msg in res["findings"] + res["warnings"]:
            lines.append("%s\t%s\t%s" % (kind, w, msg))
        for w, what, why in res["unchecked"]:
            lines.append("UNCHECKED\t%s\t%s: %s" % (w, what, why))
        if res["error"]:
            lines.append("ERROR\t\t%s" % res["error"])
        return "\n".join(lines)
    meta = data.get("meta") or {}
    src = meta.get("source") or {}
    lines.append("forge-scope-check: %s   (table %s; Jira platform %s, Jira Software %s)" % (
        res["app"], meta.get("built"), (src.get("platform") or {}).get("version", "?")[:32],
        (src.get("software") or {}).get("version", "?")))
    if res["error"]:
        lines.append("ERROR  " + res["error"])
        lines.append("result: could not read the app -> exit 2")
        return "\n".join(lines)
    lines.append("calls: %d checked, %d unchecked   declared scopes: %d" % (
        len(res["calls"]), len(res["unchecked"]), len(res["declared"])))
    for kind, w, msg in res["findings"]:
        lines.append("%-10s %s  %s" % (kind, w, msg))
    for kind, w, msg in res["warnings"]:
        lines.append("%-10s %s  %s" % ("warn " + kind.lower(), w, msg))
    for w, what, why in res["unchecked"]:
        lines.append("%-10s %s  %s: %s" % ("unchecked", w, what, why))
    code = exit_code(res)
    verdict = {0: "ok", 1: "findings", 3: "not a pass: some calls were not checked"}[code]
    lines.append("result: %d findings, %d warnings, %d unchecked -> %s (exit %d)" % (
        len(res["findings"]), len(res["warnings"]), len(res["unchecked"]), verdict, code))
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__.strip().split("\n\n")[1])
        return 2
    table = TABLE
    for a in argv:
        if a.startswith("--table="):
            table = Path(a.split("=", 1)[1])
    data, ops, index = load_table(table)
    res = check(args[0], ops, index, allow_deprecated="--allow-deprecated" in argv)
    out = report(res, data, tsv="--tsv" in argv)
    sys.stdout.buffer.write((out + "\n").encode("utf-8"))
    return exit_code(res)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
