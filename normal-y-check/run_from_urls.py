#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch normal maps by URL, decide Y+ / Y-, and invert green on the ones pointing the wrong way.

This is what the "normal-y-check" GitHub Actions workflow runs. You can run it locally too:

    python run_from_urls.py --want y+ --out result "https://example.com/brick_normal.png"
    python run_from_urls.py --want y- --out result --file local_map.png

For each image:
  * decided the way you want   -> left alone, reported as "already Y+"
  * decided the other way      -> green inverted (G -> max - G), checked again, saved to out/fixed/
  * undecided                  -> left alone, with the reason. Never flipped on a guess.
  * could not fetch or read    -> reported, and the exit code is 1

Writes out/report.md, out/verdicts.tsv and out/fixed/*.png. Nothing is written anywhere else,
and the images are never committed to the repository - the workflow only uploads `out/`.

Standard library only.
"""
import argparse
import os
import re
import struct
import sys
import urllib.parse
import urllib.request
import zlib

import normal_y_check as nyc

MAX_BYTES = 64 * 1024 * 1024   # per image
MAX_IMAGES = 20
TIMEOUT = 60
# Chunks that describe the pixels rather than change them. Kept, because inverting green
# does not change the colour space, the pixel size or the text. Everything else is dropped.
KEEP_CHUNKS = {b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"tEXt", b"zTXt", b"iTXt"}

GITHUB_BLOB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/(.+)$")


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- URLs

def normalise_url(url):
    """Return the URL to fetch, or raise FetchError with the reason.

    https only, no user:password@ in the URL. A github.com/.../blob/... page link is turned
    into its raw file, because that is the link people copy."""
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise FetchError("only https:// links are fetched (got %r)" % (parts.scheme or url))
    if parts.username or parts.password:
        raise FetchError("the link carries a user name or password; remove it")
    if not parts.hostname:
        raise FetchError("no host in the link")
    m = GITHUB_BLOB.match(url.split("?", 1)[0].split("#", 1)[0])
    if m:
        return "https://raw.githubusercontent.com/%s/%s/%s" % m.groups()
    return url


def split_urls(text):
    return [u for u in re.split(r"[\s,]+", text or "") if u]


def _open(url):
    req = urllib.request.Request(url, headers={"User-Agent": "normal-y-check"})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def fetch(url, opener=_open, limit=MAX_BYTES):
    """Download one image into memory. Refuses anything over `limit` or not a PNG."""
    try:
        with opener(url) as r:
            data = r.read(limit + 1)
    except FetchError:
        raise
    except Exception as e:   # network errors come in many classes; report them all the same way
        raise FetchError("could not fetch (%s)" % e)
    if len(data) > limit:
        raise FetchError("larger than %d MB" % (limit // (1024 * 1024)))
    if data[:8] != nyc.PNG_SIG:
        hint = ""
        if data[:3] == b"\xff\xd8\xff":
            hint = " - it is a JPEG; only PNG is read"
        elif data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
            hint = " - it is a web page, not the image; use the direct link to the file"
        raise FetchError("not a PNG file" + hint)
    return data


def file_name(url, used):
    """A safe, unique file name for the image behind `url`."""
    base = os.path.basename(urllib.parse.urlsplit(url).path) or "image.png"
    base = urllib.parse.unquote(base)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "image"
    if not base.lower().endswith(".png"):
        base += ".png"
    name = base
    i = 2
    while name.lower() in used:
        name = "%s_%d.png" % (base[:-4], i)
        i += 1
    used.add(name.lower())
    return name


# ---------------------------------------------------------------- inverting green

def _chunks(data):
    i = 8
    while i + 8 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        yield data[i + 4:i + 8], data[i + 8:i + 8 + n]
        if data[i + 4:i + 8] == b"IEND":
            return
        i += 12 + n


def _chunk(tag, body):
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def invert_green(src, dst):
    """Write `src` to `dst` with green inverted. Same size, bit depth and channels; red, blue
    and alpha are copied sample for sample."""
    width, height, ch, maxval, rows = nyc.read_png(src)
    with open(src, "rb") as f:
        original = f.read()
    ihdr = None
    kept = []
    for tag, body in _chunks(original):
        if tag == b"IHDR":
            ihdr = body
        elif tag in KEEP_CHUNKS:
            kept.append(_chunk(tag, body))
    wide = maxval > 255
    bpp = ch * (2 if wide else 1)
    raw = bytearray()
    prev = bytearray(width * bpp)
    for row in rows:
        row = list(row)
        for k in range(1, len(row), ch):
            row[k] = maxval - row[k]
        line = bytearray(struct.pack(">%dH" % len(row), *row)) if wide else bytearray(row)
        raw.append(2)   # filter "Up": smooth maps compress better against the row above
        raw += bytes((line[x] - prev[x]) & 0xFF for x in range(len(line)))
        prev = line
    # The IHDR is copied as it was; interlace is 0 because read_png refuses anything else.
    out = (nyc.PNG_SIG + _chunk(b"IHDR", ihdr[:13]) + b"".join(kept)
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b""))
    with open(dst, "wb") as f:
        f.write(out)


# ---------------------------------------------------------------- one image

def process(path, name, want, fixed_dir):
    """Decide one local PNG and fix it if needed. Returns a result dict."""
    other = nyc.Y_MINUS if want == nyc.Y_PLUS else nyc.Y_PLUS
    r = nyc.check_file(path)
    res = {"name": name, "verdict": r["verdict"], "agreement": r["agreement"], "z": r["z"],
           "size": r["size"], "action": "", "detail": r["reason"]}
    if r["verdict"] == want:
        res["action"] = "already " + want
    elif r["verdict"] == other:
        os.makedirs(fixed_dir, exist_ok=True)
        dst = os.path.join(fixed_dir, name)
        invert_green(path, dst)
        again = nyc.check_file(dst)
        if again["verdict"] != want:
            # Should not happen: inverting green negates the agreement exactly. Refuse to
            # hand over a file we could not confirm.
            os.remove(dst)
            res["action"] = "error"
            res["detail"] = "the inverted file did not check as %s (%s)" % (want, again["verdict"])
        else:
            res["action"] = "green inverted -> fixed/" + name
            res["detail"] = "re-checked: %s, agreement %+.3f" % (again["verdict"], again["agreement"])
    else:
        res["action"] = "left alone (undecided)"
    return res


# ---------------------------------------------------------------- report

def write_report(results, want, out_dir):
    fixed = sum(1 for r in results if r["action"].startswith("green inverted"))
    ok = sum(1 for r in results if r["action"].startswith("already"))
    und = sum(1 for r in results if r["action"].startswith("left alone"))
    bad = sum(1 for r in results if r["action"] in ("error", "not fetched", "unreadable"))
    lines = ["# normal-y-check", "",
             "Wanted: **%s**. %d image(s): %d fixed (green inverted), %d already %s, "
             "%d undecided (left alone), %d failed." % (want, len(results), fixed, ok, want, und, bad),
             "",
             "| image | verdict | agreement | z | size | what was done | detail |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        cells = [r["name"], r["verdict"],
                 "" if r["agreement"] is None else "%+.3f" % r["agreement"],
                 "" if r["z"] is None else "%.1f" % r["z"],
                 r["size"], r["action"], r["detail"]]
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    lines += ["",
              "Fixed files are in the `fixed/` folder of this artifact. Undecided maps were not "
              "changed: a stripe, a flat map or noise has no relief that shows the direction. "
              "See the tool's README for why."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(out_dir, "verdicts.tsv"), "w", encoding="utf-8") as f:
        f.write("image\tverdict\tagreement\tz\tsize\taction\tdetail\n")
        for r in results:
            f.write("\t".join("" if v is None else (("%+.4f" % v) if k == "agreement" else
                                                     ("%.1f" % v) if k == "z" else str(v))
                              for k, v in ((k, r[k]) for k in
                                           ("name", "verdict", "agreement", "z", "size", "action", "detail")))
                    + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    return text, bad


def _failed(name, action, detail):
    return {"name": name, "verdict": "-", "agreement": None, "z": None, "size": "",
            "action": action, "detail": detail}


def main(argv=None, opener=_open):
    ap = argparse.ArgumentParser(description="Fetch normal maps, decide Y+/Y-, invert green where needed.")
    ap.add_argument("urls", nargs="*", help="https links to PNG normal maps (spaces or commas between)")
    ap.add_argument("--file", action="append", default=[], help="a local PNG instead of a link")
    ap.add_argument("--want", required=True, choices=["y+", "y-"], help="the convention you need")
    ap.add_argument("--out", required=True, help="folder for report.md, verdicts.tsv and fixed/")
    args = ap.parse_args(argv)

    want = nyc.Y_PLUS if args.want == "y+" else nyc.Y_MINUS
    urls = [u for text in args.urls for u in split_urls(text)]
    if not urls and not args.file:
        sys.stdout.write("no image links given\n")
        return 2
    if len(urls) + len(args.file) > MAX_IMAGES:
        sys.stdout.write("at most %d images per run\n" % MAX_IMAGES)
        return 2
    out_dir = args.out
    fixed_dir = os.path.join(out_dir, "fixed")
    work = os.path.join(out_dir, ".download")
    os.makedirs(work, exist_ok=True)
    used = set()
    results = []
    try:
        jobs = [(u, None) for u in urls] + [(None, f) for f in args.file]
        for url, local in jobs:
            name = file_name(url if url else "https://x/" + os.path.basename(local), used)
            path = local
            if url:
                try:
                    data = fetch(normalise_url(url), opener=opener)
                except FetchError as e:
                    results.append(_failed(name, "not fetched", str(e)))
                    continue
                path = os.path.join(work, name)
                with open(path, "wb") as f:
                    f.write(data)
            try:
                results.append(process(path, name, want, fixed_dir))
            except (nyc.PngError, OSError) as e:
                results.append(_failed(name, "unreadable", str(e)))
    finally:
        # The downloaded originals are not part of the result; only fixed copies are.
        for n in os.listdir(work):
            os.remove(os.path.join(work, n))
        os.rmdir(work)
    text, bad = write_report(results, want, out_dir)
    sys.stdout.write(text)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
