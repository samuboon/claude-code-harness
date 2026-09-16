#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""key-expiry: report when the credentials in a tree stop working, without printing them.

    python key_expiry.py .
    python key_expiry.py . --within 60
    python key_expiry.py . --format paste      # day counts only: no paths, no file names

Exactly two kinds of credential carry their own death date inside them: a JSON Web
Token (the `exp` claim) and an X.509 certificate (`notAfter`). Both can be read
offline, with no network and no dependencies, and that is what this does.

An opaque token - a GitHub personal access token, an AWS access key - carries no date
at all. Nothing offline can tell you when it dies, and this tool does not pretend to.
That limit is the finding rather than a caveat; README.md starts with it.

It never prints the credential. It prints where it is, what kind it is, and how many
days are left. `--format paste` drops the paths as well, so the output can be pasted
somewhere public without leaking the layout of your machine.

Exit codes: 0 = nothing expires inside the window / 1 = something does, or already has
/ 2 = the scan did not happen (no target, or zero files read). A scan that read
nothing must not print a green check.

Standard library only. No network access.
"""
import argparse
import base64
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"

# Files larger than this are skipped and counted as skipped. A credential is small;
# a 200 MB binary is not worth the scan, and a partial read could split a PEM block
# in half and report a clean tree over a certificate that expired last month.
MAX_BYTES = 8 * 1024 * 1024

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", ".tox"}

# `eyJ` is base64url for `{"`, which is how every JOSE header begins. It is also how
# plenty of other base64 begins, so a match here is a candidate and nothing more:
# jwt_expiry() below refuses anything without a real JOSE header.
JWT_RE = re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.S)

UTC_TIME = 0x17
GEN_TIME = 0x18
SEQUENCE = 0x30


# ------------------------------------------------------------------ DER (X.509)
def der_read(buf, i):
    """Read one DER tag-length-value at offset `i`. Returns (tag, value, next offset)."""
    if i + 2 > len(buf):
        raise ValueError("truncated")
    tag = buf[i]
    n = buf[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        # k == 0 is the indefinite form: legal in BER, forbidden in DER, and the shape
        # a hand-written parser silently reads as "length 0" and then walks off.
        if k == 0 or k > 4 or i + k > len(buf):
            raise ValueError("bad length")
        n = int.from_bytes(buf[i:i + k], "big")
        i += k
    end = i + n
    if end > len(buf):
        raise ValueError("truncated")
    return tag, buf[i:end], end


def der_time(tag, body):
    """UTCTime / GeneralizedTime -> aware datetime. RFC 5280 requires the trailing Z."""
    s = body.decode("ascii")
    if not s.endswith("Z"):
        raise ValueError("time is not UTC: " + s)
    s = s[:-1]
    if tag == UTC_TIME:
        yy = int(s[:2])
        # RFC 5280 5.1.2.4: 50..99 is 19xx, 00..49 is 20xx. Not "add 2000".
        year = 1900 + yy if yy >= 50 else 2000 + yy
        s = s[2:]
    else:
        year = int(s[:4])
        s = s[4:]
    if len(s) == 8:      # seconds are optional in UTCTime
        s += "00"
    if len(s) != 10 or not s.isdigit():
        raise ValueError("bad time: " + s)
    return datetime(year, int(s[0:2]), int(s[2:4]), int(s[4:6]),
                    int(s[6:8]), int(s[8:10]), tzinfo=timezone.utc)


def cert_not_after(der):
    """Walk far enough into a certificate to reach Validity.notAfter, and no further.

    Rather than counting fields (which breaks on the optional version tag), this takes
    the first child SEQUENCE of tbsCertificate whose own children are exactly two Time
    values. `signature` is a SEQUENCE of an OID and `issuer` a SEQUENCE of SETs, so
    neither can be mistaken for Validity.
    """
    tag, cert, _ = der_read(der, 0)
    if tag != SEQUENCE:
        raise ValueError("not a certificate")
    tag, tbs, _ = der_read(cert, 0)
    if tag != SEQUENCE:
        raise ValueError("not a certificate")
    i = 0
    while i < len(tbs):
        tag, body, i = der_read(tbs, i)
        if tag != SEQUENCE:
            continue
        times = []
        j = 0
        try:
            while j < len(body):
                t, b, j = der_read(body, j)
                if t not in (UTC_TIME, GEN_TIME):
                    times = []
                    break
                times.append((t, b))
        except ValueError:
            continue
        if len(times) == 2:
            return der_time(*times[1])
    raise ValueError("no validity field")


# ------------------------------------------------------------------------- JWT
def b64url(seg):
    return base64.urlsafe_b64decode(seg + b"=" * (-len(seg) % 4))


def jwt_expiry(token):
    """The `exp` claim of a JWT, as an aware datetime. Raises if this is not a JWT."""
    parts = token.split(b".")
    if len(parts) != 3:
        raise ValueError("not three segments")
    head = json.loads(b64url(parts[0]))
    if not isinstance(head, dict) or "alg" not in head:
        raise ValueError("no JOSE header")
    claims = json.loads(b64url(parts[1]))
    if not isinstance(claims, dict):
        raise ValueError("payload is not an object")
    exp = claims.get("exp")
    # bool is an int in Python, and `"exp": true` is not a date.
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise ValueError("no exp claim")
    return datetime.fromtimestamp(float(exp), tz=timezone.utc)


# ------------------------------------------------------------------- scanning
def views(data):
    """The file as bytes, and - if it holds NULs - again with them removed.

    A UTF-16LE file stores ASCII as `t\\x00o\\x00k\\x00`, so an ASCII pattern never
    matches it. This is the same blind spot leak-scan exists for, handled the cheap
    way because both things we look for are ASCII.
    """
    yield data, False
    if b"\x00" in data:
        stripped = data.replace(b"\x00", b"")
        if stripped and stripped != data:
            yield stripped, True


def scan_bytes(data):
    """-> list of (line, kind, expires, note). Never returns the credential itself."""
    found = []
    seen = set()
    for buf, wide in views(data):
        for regex, kind in ((JWT_RE, "jwt"), (PEM_RE, "x509")):
            for m in regex.finditer(buf):
                blob = m.group(0)
                try:
                    if kind == "jwt":
                        when = jwt_expiry(blob)
                        # Identity is the header and payload, not the whole match: the
                        # signature pattern also swallows whatever follows the token, so
                        # the same JWT read twice (once per view) is not byte-identical.
                        key = blob.rsplit(b".", 1)[0]
                    else:
                        key = re.sub(rb"[^A-Za-z0-9+/=]", b"", m.group(1))
                        when = cert_not_after(base64.b64decode(key, validate=True))
                except Exception:
                    continue          # a candidate that is not one of ours
                if (kind, key) in seen:
                    continue
                seen.add((kind, key))
                note = "%d bytes" % len(blob)
                if wide:
                    note += ", utf-16le"
                found.append((buf.count(b"\n", 0, m.start()) + 1, kind, when, note))
    return found


def walk(root):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            yield p


def scan_tree(root):
    """-> (findings, files_read, files_skipped). findings hold paths relative to root."""
    findings = []
    read = skipped = 0
    for p in walk(root):
        try:
            if p.stat().st_size > MAX_BYTES:
                skipped += 1
                continue
            data = p.read_bytes()
        except OSError:
            skipped += 1
            continue
        read += 1
        try:
            rel = p.relative_to(root if root.is_dir() else root.parent).as_posix()
        except ValueError:
            rel = p.as_posix()
        for line, kind, when, note in scan_bytes(data):
            findings.append((rel, line, kind, when, note))
    return findings, read, skipped


def days_left(when, now):
    return int(math.floor((when - now).total_seconds() / 86400.0))


# ----------------------------------------------------------------------- CLI
def report(findings, now, within, fmt, out):
    rows = sorted(((days_left(w, now), r, l, k, w, n) for r, l, k, w, n in findings))
    due = [x for x in rows if x[0] <= within]
    if fmt == "paste":
        # Safe to paste in public: kinds and day counts, nothing that names your machine.
        out.write("# key-expiry %s: %d credential(s) carry a date, %d expire within %d days\n"
                  % (VERSION, len(rows), len(due), within))
        for d, _rel, _line, kind, _w, _n in rows:
            out.write("%s\t%d\n" % (kind, d))
    elif fmt == "github":
        for d, rel, line, kind, w, _n in due:
            out.write("::warning file=%s,line=%d::%s expires in %d day(s) (%s)\n"
                      % (rel, line, kind, d, w.strftime("%Y-%m-%dT%H:%M:%SZ")))
    else:
        out.write("path\tline\tkind\texpires\tdays_left\tnote\n")
        for d, rel, line, kind, w, n in rows:
            out.write("%s\t%d\t%s\t%s\t%d\t%s\n"
                      % (rel, line, kind, w.strftime("%Y-%m-%dT%H:%M:%SZ"), d, n))
    return due


def main(argv=None):
    ap = argparse.ArgumentParser(description="When do the credentials in this tree stop working?")
    ap.add_argument("path", nargs="?", help="file or directory to scan")
    ap.add_argument("--within", type=int, default=30,
                    help="exit 1 if something expires within this many days (default 30)")
    ap.add_argument("--format", choices=("tsv", "paste", "github"), default="tsv")
    ap.add_argument("--now", help="ISO-8601 instant to measure from, for reproducible reports")
    ap.add_argument("--version", action="version", version=VERSION)
    a = ap.parse_args(argv)

    if not a.path:
        print("key-expiry: no path given; nothing was scanned", file=sys.stderr)
        return 2
    root = Path(a.path)
    if not root.exists():
        print("key-expiry: no such path: %s" % a.path, file=sys.stderr)
        return 2
    if a.now:
        now = datetime.fromisoformat(a.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    findings, read, skipped = scan_tree(root)
    if read == 0:
        print("key-expiry: read 0 files under %s; this is not a clean result" % a.path,
              file=sys.stderr)
        return 2
    due = report(findings, now, a.within, a.format, sys.stdout)
    print("key-expiry: %d file(s) read, %d skipped, %d dated credential(s), %d due within %d day(s)"
          % (read, skipped, len(findings), len(due), a.within), file=sys.stderr)
    return 1 if due else 0


if __name__ == "__main__":
    sys.exit(main())
