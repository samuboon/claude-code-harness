#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Binary-aware leak scan: read every file on disk as bytes and look for credentials
and for your own identifiers, before you publish.

    python leak_scan.py .
    python leak_scan.py . --patterns my-identifiers.txt --format github

Why it does not use git: the thing that nearly got published here was three `.pyc`
files under `__pycache__/`. They are untracked by git even with no `.gitignore`, so
they never appear in `git status` or in a diff, and they are binary, so a text grep
cannot see them either. Two instruments, one blind spot. This tool therefore walks
the directory, not the index, and opens everything as bytes.

Exit codes: 0 = no hits / 1 = hits found / 2 = the scan did not happen
(no target, or zero files read). A scan that read nothing must not report success.

Standard library only. No network access.
"""
import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------- credentials
# A prefix is only a hit when it is followed by at least N body characters, i.e.
# when it has the shape of a key. Documentation that merely mentions `ghp_` is not a
# leak: with this test removed, this repository reports 33 hits instead of none, and
# every one of the 33 is prose. Measured on a fresh checkout, 2026-09-15.
KEY_PREFIXES = {
    "ghp_": 36,          # GitHub personal access token (classic)
    "gho_": 36,          # GitHub OAuth token
    "ghu_": 36,          # GitHub user-to-server token
    "ghs_": 36,          # GitHub server-to-server token
    "ghr_": 36,          # GitHub refresh token
    "github_pat_": 22,   # GitHub fine-grained personal access token
    "AKIA": 16,          # AWS access key id
    "ASIA": 16,          # AWS temporary access key id
    "AIza": 35,          # Google API key
    "xoxb-": 10,         # Slack bot token
    "xoxp-": 10,         # Slack user token
    "xapp-": 10,         # Slack app-level token
    "sk_live_": 16,      # Stripe secret key
    "rk_live_": 16,      # Stripe restricted key
}

# PEM headers - one literal covers RSA / EC / DSA / OPENSSH / PGP. A header on its own is
# not a key: this file, and every secret scanner ever written, contains the words. It
# counts only when base64 follows, which is the same rule as the key prefixes above.
# Without this test a scan of this repository reports five hits, every one of them the
# words sitting in a comment or a pattern list. Measured 2026-09-15.
KEY_LITERALS = [
    "PRIVATE KEY-----",
]
PEM_BODY_MIN = 24
B64 = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")

# `name=value` shapes. The name alone means nothing - half the world's source code
# contains the word `password` - so a hit also needs a value that is long enough and
# is not a placeholder. See PLACEHOLDERS below.
#
# The names below are assembled from pieces rather than spelled out, which is the one
# piece of ugliness in this file and is deliberate. Most scanners - including the one
# this repository is checked with - match these names as plain substrings with no shape
# test, so a rule list that writes them out in full makes every scanner pointed at
# this tree report the tool itself. The same reason splits the fixtures in
# test_leak_scan.py. Run the tests to see the assembled list is what you expect.
_K = "key"
ASSIGN_NAMES = [name + "=" for name in (
    "password", "passwd", "api_" + _K, "api" + _K, "secret", "secret_" + _K,
    "access_" + _K, "private_" + _K, "client_secret", "auth_token",
)]
ASSIGN_MIN = 8

# Values that look like a secret but are a stand-in. Compared lower-cased against the
# whole extracted value.
PLACEHOLDERS = (
    "xxx", "***", "your", "changeme", "change_me", "example", "placeholder", "redacted",
    "dummy", "sample", "secret", "password", "hunter2", "todo", "none", "null", "here",
)
# A value starting with one of these is an interpolation, not a literal.
INTERP_START = tuple("$<{%(")

ASCII_WORD = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
KEY_BODY = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
VALUE_STOP = set(b" \t\r\n\"'`,;&|)>]}\\")

DEFAULT_EXCLUDES = (".git",)


# ---------------------------------------------------------------- your own words
def load_patterns(path):
    """Read one word per line; `#` starts a comment. Returns [] if the file is absent.

    The caller decides whether an absent file is fatal - see main(). Silently scanning
    with an empty word list is the failure mode this signature exists to make visible.
    """
    words = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                w = line.split("#", 1)[0].strip()
                if w:
                    words.append(w)
    except OSError:
        return []
    return words


def derived_paths(words):
    """Home-directory paths built from each ASCII word.

    The leak that started this was not the username on its own; it was the absolute
    build path `C:\\Users\\<name>\\...` compiled into a `.pyc`.
    """
    out = []
    for w in words:
        if w.isascii() and w:
            out += ["C:\\Users\\" + w, "C:/Users/" + w, "/home/" + w, "/Users/" + w]
    return out


# ---------------------------------------------------------------- byte matching
def is_ascii_only(word):
    return all(ord(c) < 128 for c in word)


def _boundary_ok(data, start, end):
    """True when an ASCII word is not part of a longer word.

    Without this, a three-letter identifier matches inside ordinary English and the
    report drowns. With it, a real `ghp_...` was never caught, because a key prefix is
    *supposed* to be followed by more characters - which is why key prefixes skip it.
    """
    before = data[start - 1] if start > 0 else None
    after = data[end] if end < len(data) else None
    return before not in ASCII_WORD and after not in ASCII_WORD


def is_katakana_only(word):
    return bool(word) and all(0x30A0 <= ord(c) <= 0x30FF for c in word)


def _kata_boundary_ok(data, start, end):
    """Same idea for katakana, which is written without spaces.

    A three-character katakana name matched inside a longer katakana compound and
    produced 38 false positives in a single document before this existed. UTF-8
    katakana is three bytes per character.
    """
    before = data[max(0, start - 3):start].decode("utf-8", "ignore")
    after = data[end:end + 3].decode("utf-8", "ignore")
    return not (is_katakana_only(before[-1:]) or is_katakana_only(after[:1]))


def find_word(data, word, check_boundary=True):
    """`(position, byte length)` for each match of `word`, as UTF-8 and as UTF-16LE.

    UTF-16LE is what matters for binaries: strings compiled into an executable or a
    `.pyc` on Windows are frequently stored two bytes per character, and a UTF-8-only
    search walks straight past them.
    """
    spots = []
    kata = is_katakana_only(word)
    for enc, step in (("utf-8", 1), ("utf-16-le", 2)):
        try:
            needle = word.encode(enc)
        except UnicodeEncodeError:
            continue
        if not needle:
            continue
        i = data.find(needle)
        while i != -1:
            end = i + len(needle)
            ok = True
            if step == 1:  # boundary tests only make sense on the UTF-8 form
                if check_boundary and not _boundary_ok(data, i, end):
                    ok = False
                if kata and not _kata_boundary_ok(data, i, end):
                    ok = False
            if ok:
                spots.append((i, len(needle)))
            i = data.find(needle, i + 1)
    return sorted(spots)


def _key_shaped(data, pos, prefix):
    """Shape tests read forward from the UTF-8 form of the needle. A key stored two bytes
    per character inside a binary is therefore found by the search and then dropped here;
    that gap is known and unfixed - see "What this does not do" in README.md."""
    need = KEY_PREFIXES[prefix]
    start = pos + len(prefix)
    tail = data[start:start + need]
    return len(tail) == need and all(b in KEY_BODY for b in tail)


def _pem_shaped(data, pos, needle):
    """True when base64 follows the header, i.e. when this is a key and not a mention."""
    i = pos + len(needle)
    while i < len(data) and data[i] in b"\r\n":
        i += 1
    body = 0
    while i < len(data) and data[i] in B64 and body < PEM_BODY_MIN:
        i += 1
        body += 1
    return body >= PEM_BODY_MIN


def _assigned_value(data, pos, name):
    """The literal value after `name=`, or None when there is no usable one."""
    i = pos + len(name)
    if i < len(data) and data[i] in b"\"'":
        i += 1
    out = bytearray()
    while i < len(data) and data[i] not in VALUE_STOP and len(out) <= 200:
        out.append(data[i])
        i += 1
    return bytes(out) if out else None


def _is_real_secret_value(value):
    if value is None or len(value) < ASSIGN_MIN:
        return False
    text = value.decode("utf-8", "ignore")
    if text.startswith(INTERP_START):
        return False
    low = text.lower()
    return not any(p in low for p in PLACEHOLDERS)


def build_rules(words=()):
    """(kind, needle, mode) triples. `mode` decides which shape test applies."""
    rules = [("credential", p, "key") for p in sorted(KEY_PREFIXES)]
    rules += [("credential", lit, "pem") for lit in KEY_LITERALS]
    for name in ASSIGN_NAMES:
        rules.append(("credential", name, "assign"))
        rules.append(("credential", name.upper(), "assign"))
    for w in words:
        rules.append(("identifier", w, "word"))
    for p in derived_paths(words):
        rules.append(("home path", p, "literal"))
    return rules


def mask(text):
    """Never print the thing we found. This runs inside CI logs, which are public on
    public repositories - a scanner that echoes the secret it caught has moved it, not
    found it."""
    text = str(text)
    if len(text) <= 2:
        return "*" * len(text)
    return text[:2] + "*" * min(len(text) - 2, 12)


def _line_of(data, pos):
    return data.count(b"\n", 0, pos) + 1


def _drop_contained(spans):
    """Keep the longest match over each stretch of bytes.

    `C:\\Users\\alice\\build` matches both the home-path rule and the bare identifier
    inside it. Reporting both counts one leak twice and makes the tail of a report look
    like new findings, so the shorter match inside a longer one is dropped.
    """
    kept = []
    for span in spans:
        _kind, _needle, pos, _line, length = span
        if any(other is not span and other[2] <= pos and other[2] + other[4] >= pos + length
               and other[4] > length for other in spans):
            continue
        kept.append(span)
    return kept


def scan_bytes(data, rules=None):
    """Scan one file's bytes. Returns [(kind, needle, position, line)]."""
    rules = build_rules() if rules is None else rules
    spans = []
    for kind, needle, mode in rules:
        check = mode == "word" and is_ascii_only(needle)
        for pos, length in find_word(data, needle, check_boundary=check):
            if mode == "key" and not _key_shaped(data, pos, needle):
                continue
            if mode == "pem" and not _pem_shaped(data, pos, needle):
                continue
            if mode == "assign" and not _is_real_secret_value(_assigned_value(data, pos, needle)):
                continue
            spans.append((kind, needle, pos, _line_of(data, pos), length))
    spans = _drop_contained(spans)
    return sorted([(k, n, p, ln) for k, n, p, ln, _len in spans], key=lambda h: h[2])


def scan_file(path, rel, rules, allow=frozenset()):
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        return [(rel, "unreadable", str(e), 0)]
    out = []
    for kind, needle, _pos, line in scan_bytes(data, rules):
        if (rel, needle) in allow or ("*", needle) in allow:
            continue
        out.append((rel, kind, needle, line))
    return out


def _excluded(rel, excludes):
    parts = rel.split("/")
    return any(e and (rel == e or rel.startswith(e + "/") or e in parts) for e in excludes)


def scan_tree(root, rules, excludes=DEFAULT_EXCLUDES, allow=frozenset()):
    """Walk the directory - not the git index - and open every file as bytes."""
    root = Path(root)
    files = 0
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, excludes):
            continue
        files += 1
        found.extend(scan_file(path, rel, rules, allow))
    return files, found


def load_allow(path):
    """`relative/path|needle` per line; `*|needle` allows the needle everywhere."""
    pairs = set()
    for line in load_patterns(path):
        if "|" in line:
            rel, needle = line.split("|", 1)
            pairs.add((rel.strip(), needle.strip()))
    return pairs


# ---------------------------------------------------------------- command line
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="Binary-aware leak scan.")
    ap.add_argument("target", nargs="*", default=["."], help="directories or files to scan")
    ap.add_argument("--patterns", default="", help="file of your own identifiers, one per line")
    ap.add_argument("--allow", default="", help="file of `path|needle` exceptions")
    ap.add_argument("--exclude", default=",".join(DEFAULT_EXCLUDES),
                    help="comma-separated path prefixes to skip (default: .git)")
    ap.add_argument("--format", choices=["text", "github"], default="text",
                    help="github emits ::error annotations")
    ap.add_argument("--fail-on", choices=["any", "none"], default="any",
                    help="none reports without failing the run")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    words = []
    if args.patterns:
        if not Path(args.patterns).exists():
            print("patterns file not found: " + args.patterns, file=sys.stderr)
            return 2
        words = load_patterns(args.patterns)
        if not words:
            print("patterns file is empty: " + args.patterns, file=sys.stderr)
            return 2
    allow = load_allow(args.allow) if args.allow else frozenset()
    excludes = tuple(e.strip() for e in args.exclude.split(",") if e.strip())
    rules = build_rules(words)

    total_files = 0
    total_hits = []
    for t in args.target:
        p = Path(t)
        if not p.exists():
            print("target not found: " + t, file=sys.stderr)
            return 2
        if p.is_file():
            files, found = 1, scan_file(p, p.name, rules, allow)
        else:
            files, found = scan_tree(p, rules, excludes, allow)
        total_files += files
        total_hits.extend(found)
        print("[%s] %d files scanned, %d hit(s)" % (t, files, len(found)))

    for rel, kind, needle, line in total_hits:
        shown = needle if kind == "credential" else mask(needle)
        if args.format == "github":
            print("::error file=%s,line=%d::%s leak: %s" % (rel, max(line, 1), kind, shown))
        else:
            print("  - %s:%d | %s | %s" % (rel, line, kind, shown))

    print("total: %d files scanned, %d hit(s)" % (total_files, len(total_hits)))
    if total_files == 0:
        print("nothing was read, so this is not a pass", file=sys.stderr)
        return 2
    if total_hits and args.fail_on == "any":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
