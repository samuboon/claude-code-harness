#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tell whether a PNG actually tiles, by asking whether its wrap is the worst edge in it.

    python tile_seam.py <file-or-folder> [...]

A texture is "seamless" when the right edge continues into the left edge and the bottom
continues into the top. The obvious test - measure the step across that wrap and compare it
to a fixed threshold - is wrong, and we know because we shipped it. A woven pattern with a
hard rib in it steps just as far between two ordinary neighbouring columns, so the fixed
threshold calls a perfectly good tile broken.

So this measures the wrap step **against the image's own distribution of neighbour steps**.
Every adjacent column pair in the image gives one number; the wrap gives one more. If the
wrap is larger than all of them, the wrap is the worst edge in the picture, and that is a
seam. If it sits inside the distribution, the pattern is simply that contrasty everywhere.

Standard library only. PNG only (8/16-bit, colour types 0/2/3/4/6, non-interlaced).

Exit: 0 = nothing called a seam / 1 = at least one seam / 2 = nothing could be read.
"""
import argparse
import operator
import os
import struct
import sys
import zlib
from pathlib import Path

PNG_SIG = b"\x89PNG\r\n\x1a\n"

# The three verdicts, worst first. `ranked()` relies on this order.
SEAM, SUSPECT, OK = "seam", "suspect", "ok"
SEVERITY = {SEAM: 2, SUSPECT: 1, OK: 0}

# A wrap that beats this share of the image's own neighbour steps, without beating all of
# them, is reported as `suspect` rather than `seam`. 0.99 is a choice, not a measurement;
# --strict lowers it so you can see what sits just underneath.
SUSPECT_RANK = 0.99

# What a fixed-threshold test would use, for --naive. 8 of 255 is roughly where a step
# stops being invisible on a monitor. It is here to be shown up, not to be relied on.
NAIVE_THRESHOLD = 8.0

CHANNEL_NAMES = {1: ("gray",), 2: ("gray", "alpha"), 3: ("r", "g", "b"), 4: ("r", "g", "b", "alpha")}


class PngError(ValueError):
    """The file is not a PNG this tool can read. The message says which part gave up."""


class Image(object):
    __slots__ = ("width", "height", "planes", "names", "path")

    def __init__(self, width, height, planes, names, path=""):
        self.width = width
        self.height = height
        self.planes = planes          # list of bytes, each width*height, 8-bit samples
        self.names = names            # channel names, same length as planes
        self.path = path


# --- reading a PNG ------------------------------------------------------------

def _chunks(data):
    """Walk the chunk list. Lengths are trusted only as far as the file actually goes."""
    pos = len(PNG_SIG)
    n = len(data)
    while pos + 8 <= n:
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        start = pos + 8
        end = start + length
        if end > n:
            raise PngError("chunk %r runs past the end of the file" % ctype.decode("latin-1"))
        yield ctype, data[start:end]
        pos = end + 4             # skip the CRC
        if ctype == b"IEND":
            return
    raise PngError("no IEND chunk")


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, height, stride, bpp):
    """Undo the per-scanline PNG filters in place. Returns height*stride bytes."""
    out = bytearray(height * stride)
    prev = bytes(stride)
    pos = 0
    need = height * (stride + 1)
    if len(raw) < need:
        raise PngError("decompressed to %d bytes, expected %d" % (len(raw), need))
    for y in range(height):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(bpp):
                line[i] = (line[i] + (prev[i] >> 1)) & 0xFF
            for i in range(bpp, stride):
                line[i] = (line[i] + ((line[i - bpp] + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(bpp):
                line[i] = (line[i] + prev[i]) & 0xFF
            for i in range(bpp, stride):
                line[i] = (line[i] + _paeth(line[i - bpp], prev[i], prev[i - bpp])) & 0xFF
        else:
            raise PngError("unknown scanline filter %d on row %d" % (ft, y))
        off = y * stride
        out[off:off + stride] = line
        prev = bytes(line)
    return bytes(out)


def _expand_low_depth(rows, width, height, depth, stride):
    """1/2/4-bit samples -> one byte each, scaled so full-scale stays 255."""
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    scale = 255 // mask
    out = bytearray(width * height)
    for y in range(height):
        src = y * stride
        dst = y * width
        x = 0
        for i in range(stride):
            byte = rows[src + i]
            for k in range(per_byte):
                if x >= width:
                    break
                shift = 8 - depth * (k + 1)
                out[dst + x] = ((byte >> shift) & mask) * scale
                x += 1
    return bytes(out)


def _split_planes(rows, width, height, stride, nch, depth):
    """Pull each channel out as its own width*height byte plane (16-bit keeps the high byte)."""
    step = nch * (2 if depth == 16 else 1)
    planes = []
    for c in range(nch):
        first = c * (2 if depth == 16 else 1)
        buf = bytearray(width * height)
        for y in range(height):
            src = rows[y * stride:(y + 1) * stride]
            buf[y * width:(y + 1) * width] = src[first::step][:width]
        planes.append(bytes(buf))
    return planes


def read_png(path):
    """Decode a PNG into 8-bit channel planes. Raises PngError on anything unsupported."""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIG):
        raise PngError("not a PNG (signature)")
    width = height = depth = ctype = interlace = None
    palette = None
    trns = None
    idat = []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            if len(body) < 13:
                raise PngError("IHDR is %d bytes, expected 13" % len(body))
            width, height, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if width is None:
        raise PngError("no IHDR chunk")
    if width == 0 or height == 0:
        raise PngError("zero-sized image (%dx%d)" % (width, height))
    if interlace:
        raise PngError("Adam7-interlaced PNGs are not supported; re-save without interlacing")
    if not idat:
        raise PngError("no IDAT chunk")
    if ctype not in (0, 2, 3, 4, 6):
        raise PngError("unknown colour type %d" % ctype)
    nch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    if ctype in (2, 4, 6) and depth not in (8, 16):
        raise PngError("colour type %d with bit depth %d" % (ctype, depth))
    if ctype in (0, 3) and depth not in (1, 2, 4, 8, 16):
        raise PngError("colour type %d with bit depth %d" % (ctype, depth))
    if ctype == 3 and depth == 16:
        raise PngError("palette images cannot be 16-bit")

    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise PngError("the image data would not inflate (%s)" % exc)

    bits = width * nch * depth
    stride = (bits + 7) // 8
    bpp = max(1, (nch * depth + 7) // 8)
    rows = _unfilter(raw, height, stride, bpp)

    if depth < 8:
        index = _expand_low_depth(rows, width, height, depth, stride)
        planes = [index]
        nch = 1
    else:
        planes = _split_planes(rows, width, height, stride, nch, depth)

    if ctype == 3:
        if palette is None:
            raise PngError("palette image with no PLTE chunk")
        entries = len(palette) // 3
        if entries == 0:
            raise PngError("PLTE chunk is empty")
        # The plane currently holds palette indices; low-depth expansion scaled them, so undo it.
        mask = (1 << depth) - 1
        scale = 255 // mask if depth < 8 else 1
        idx = planes[0]
        r = bytearray(len(idx))
        g = bytearray(len(idx))
        b = bytearray(len(idx))
        a = bytearray(len(idx))
        has_alpha = trns is not None and len(trns) > 0
        for i, v in enumerate(idx):
            e = (v // scale) if scale > 1 else v
            if e >= entries:
                raise PngError("palette index %d but only %d entries" % (e, entries))
            r[i] = palette[e * 3]
            g[i] = palette[e * 3 + 1]
            b[i] = palette[e * 3 + 2]
            a[i] = trns[e] if (has_alpha and e < len(trns)) else 255
        planes = [bytes(r), bytes(g), bytes(b)] + ([bytes(a)] if has_alpha else [])

    names = CHANNEL_NAMES[len(planes)]
    return Image(width, height, planes, names, str(path))


# --- measuring ----------------------------------------------------------------

def _mean_abs(a, b):
    """Mean of |a[i]-b[i]| over two equal-length byte strings."""
    return sum(map(abs, map(operator.sub, a, b))) / len(a)


def column_steps(plane, width, height):
    """(wrap, steps) for the left/right wrap. steps has one entry per adjacent column pair."""
    if width < 2:
        return None
    acc = [0] * (width - 1)
    for y in range(height):
        row = plane[y * width:(y + 1) * width]
        acc = [a + d for a, d in zip(acc, map(abs, map(operator.sub, row[:-1], row[1:])))]
    steps = [a / height for a in acc]
    wrap = _mean_abs(plane[width - 1::width], plane[0::width])
    return wrap, steps


def row_steps(plane, width, height):
    """(wrap, steps) for the top/bottom wrap. steps has one entry per adjacent row pair."""
    if height < 2:
        return None
    steps = []
    for y in range(height - 1):
        steps.append(_mean_abs(plane[y * width:(y + 1) * width], plane[(y + 1) * width:(y + 2) * width]))
    wrap = _mean_abs(plane[(height - 1) * width:height * width], plane[0:width])
    return wrap, steps


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def judge(wrap, steps, suspect_rank=SUSPECT_RANK):
    """Compare one wrap against the image's own neighbour steps.

    Returns (verdict, ratio, rank). `ratio` is the wrap over the median step - readable, but
    not what decides anything. `rank` is the share of neighbour steps the wrap beats, and
    that is what decides: beat all of them and the wrap is the worst edge in the picture.
    """
    n = len(steps)
    worst = max(steps)
    rank = sum(1 for s in steps if s < wrap) / n
    med = _median(steps)
    if med > 0:
        ratio = wrap / med
    else:
        ratio = 0.0 if wrap == 0 else float("inf")
    if wrap == 0.0:
        return OK, ratio, rank
    if wrap > worst:
        return SEAM, ratio, rank
    if rank >= suspect_rank:
        return SUSPECT, ratio, rank
    return OK, ratio, rank


def _axis(image, measure, suspect_rank):
    """Run one axis over every channel and keep the worst channel's answer."""
    best = None
    for plane, name in zip(image.planes, image.names):
        got = measure(plane, image.width, image.height)
        if got is None:
            return None
        wrap, steps = got
        verdict, ratio, rank = judge(wrap, steps, suspect_rank)
        row = {"verdict": verdict, "ratio": ratio, "rank": rank, "wrap": wrap,
               "worst": max(steps), "median": _median(steps), "channel": name}
        key = (SEVERITY[verdict], rank, wrap)
        if best is None or key > best[0]:
            best = (key, row)
    return None if best is None else best[1]


def analyse(image, suspect_rank=SUSPECT_RANK):
    """Both axes of one image. `x` is the left/right wrap, `y` the top/bottom wrap."""
    x = _axis(image, column_steps, suspect_rank)
    y = _axis(image, row_steps, suspect_rank)
    present = [a for a in (x, y) if a is not None]
    overall = OK
    for a in present:
        if SEVERITY[a["verdict"]] > SEVERITY[overall]:
            overall = a["verdict"]
    return {"path": image.path, "width": image.width, "height": image.height,
            "x": x, "y": y, "overall": overall}


def naive_verdict(result, threshold=NAIVE_THRESHOLD):
    """What a fixed-threshold edge test would have said. Kept so you can see it be wrong."""
    for a in (result["x"], result["y"]):
        if a is not None and a["wrap"] >= threshold:
            return SEAM
    return OK


# --- walking and printing -----------------------------------------------------

def collect(paths):
    """Every .png under the given files and folders, sorted, with no duplicates."""
    out = []
    seen = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = sorted(q for q in p.rglob("*") if q.is_file() and q.suffix.lower() == ".png")
        elif p.is_file():
            found = [p]
        else:
            out.append((p, "no such file or folder"))
            continue
        for q in found:
            key = os.path.normcase(str(q.resolve()))
            if key not in seen:
                seen.add(key)
                out.append((q, None))
    return out


def _cell(a):
    if a is None:
        return "n/a"
    ratio = "inf" if a["ratio"] == float("inf") else "%.2f" % a["ratio"]
    return "%-7s x%-6s %3.0f%% %s" % (a["verdict"], ratio, a["rank"] * 100, a["channel"])


def render(results, failures, root, naive=None):
    lines = []
    lines.append("tile-seam: %d PNG(s) under %s" % (len(results), root))
    lines.append("")
    if results:
        width = max(len(r["shown"]) for r in results)
        header = "%-*s  %-9s  %-24s  %-24s" % (width, "file", "size", "left/right wrap", "top/bottom wrap")
        lines.append(header)
        lines.append("-" * len(header))
        for r in results:
            lines.append("%-*s  %-9s  %-24s  %-24s" % (
                width, r["shown"], "%dx%d" % (r["width"], r["height"]), _cell(r["x"]), _cell(r["y"])))
        lines.append("")
        seams = [r for r in results if r["overall"] == SEAM]
        suspects = [r for r in results if r["overall"] == SUSPECT]
        lines.append("%d seam, %d suspect, %d ok" % (len(seams), len(suspects),
                                                     len(results) - len(seams) - len(suspects)))
        if naive is not None:
            flagged = [r for r in results if naive_verdict(r, naive) == SEAM]
            disagree = [r for r in flagged if r["overall"] == OK]
            lines.append("a fixed threshold of %.1f/255 on the wrap alone would call %d of these seamed, "
                         "%d of which this tool calls ok" % (naive, len(flagged), len(disagree)))
    if failures:
        lines.append("")
        lines.append("%d file(s) could not be read:" % len(failures))
        for path, why in failures:
            lines.append("  %s - %s" % (path, why))
    return "\n".join(lines)


def render_tsv(results):
    out = ["file\twidth\theight\taxis\tverdict\twrap\tmedian\tworst\tratio\trank\tchannel"]
    for r in results:
        for axis in ("x", "y"):
            a = r[axis]
            if a is None:
                continue
            out.append("\t".join([
                r["shown"], str(r["width"]), str(r["height"]), axis, a["verdict"],
                "%.4f" % a["wrap"], "%.4f" % a["median"], "%.4f" % a["worst"],
                ("inf" if a["ratio"] == float("inf") else "%.4f" % a["ratio"]),
                "%.4f" % a["rank"], a["channel"]]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Say whether a PNG tiles, by comparing its wrap against its own neighbour steps.")
    ap.add_argument("paths", nargs="+", help="PNG files or folders to walk")
    ap.add_argument("--tsv", action="store_true", help="one row per file per axis, tab separated")
    ap.add_argument("--strict", action="store_true",
                    help="report `suspect` from the 90th percentile instead of the 99th")
    ap.add_argument("--naive", nargs="?", type=float, const=NAIVE_THRESHOLD, default=None,
                    metavar="STEP",
                    help="also print what a fixed threshold on the raw wrap step would have said")
    args = ap.parse_args(argv)

    suspect_rank = 0.90 if args.strict else SUSPECT_RANK
    found = collect(args.paths)
    results = []
    failures = []
    for path, why in found:
        if why:
            failures.append((str(path), why))
            continue
        try:
            image = read_png(path)
        except (PngError, OSError, struct.error) as exc:
            failures.append((str(path), str(exc)))
            continue
        r = analyse(image, suspect_rank)
        r["shown"] = str(path)
        results.append(r)

    if len(args.paths) == 1:
        root = str(args.paths[0])
    else:
        try:
            root = os.path.commonpath([str(Path(p)) for p in args.paths])
        except ValueError:          # different drives, or a mix of absolute and relative
            root = "%d given paths" % len(args.paths)
    if args.tsv:
        print(render_tsv(results))
    else:
        print(render(results, failures, root, args.naive))

    if not results:
        return 2
    return 1 if any(r["overall"] == SEAM for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
