#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tell a Y+ (OpenGL) normal map from a Y- (DirectX) one, from the pixels alone.

    python normal_y_check.py path/to/maps                # one line per PNG
    python normal_y_check.py pack/ --expect y+           # exit 1 if a map is decided the other way
    python normal_y_check.py pack/ --tsv                 # tab-separated, one row per file

Standard library only. No engine, no PIL, no install.

The idea
--------
A tangent-space normal map is a picture of a surface's slope. Red is the slope across,
green is the slope down, and the two conventions disagree only about the sign of green.

A real slope field has no curl. Going down one pixel changes the across-slope by exactly
as much as going across one pixel changes the down-slope (d2h/dx dy = d2h/dy dx). Read the
green channel with the right sign and those two mixed derivatives agree; read it with the
wrong sign and they come out equal and opposite. So at every interior pixel we take

    a = change of (-R/B) from the row above to the row below    ~ d2h/dx dy
    b = change of (+G/B) from the pixel left to the pixel right  ~ d2h/dy dx under Y+

and ask which sign a and b agree with. That is the whole test. It needs relief that bends
in both directions at once; a stripe, a flat map, or pure noise has none, and for those the
answer is `undecided` - never a guess.

Exit codes: 0 = done (and, with --expect, nothing contradicted it and at least one map was
decided) / 1 = with --expect, at least one map was decided the other way / 2 = usage error,
or a file could not be read / 3 = with --expect, no map could be decided at all.
"""
import argparse
import math
import os
import struct
import sys
import zlib

Y_PLUS = "Y+"
Y_MINUS = "Y-"
UNDECIDED = "undecided"

# A map is decided only when both hold. Tuned on synthetic and real maps; see README.
MIN_Z = 6.0            # the agreement must stand this many standard errors clear of zero
MIN_AGREEMENT = 0.25   # |cosine| between the two mixed derivatives
MIN_PAIRS = 16         # interior pixels with all four neighbours usable
MIN_VALID = 0.5        # share of pixels that decode to an upward-facing normal
NZ_FLOOR = 0.05        # below this the blue channel is treated as unused

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(Exception):
    pass


# ---------------------------------------------------------------- PNG reading

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path):
    """Return (width, height, channels, maxval, rows); rows yields one list of samples per row.

    8- and 16-bit RGB / RGBA, filters 0-4, non-interlaced. Anything else raises PngError
    with the reason, rather than being guessed at."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != PNG_SIG:
        raise PngError("not a PNG file")
    i = 8
    ihdr = None
    idat = []
    while i + 8 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        tag = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + n]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body[:13])
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
        i += 12 + n
    if ihdr is None:
        raise PngError("no IHDR chunk")
    width, height, depth, ctype, _comp, _filt, interlace = ihdr
    if ctype not in CHANNELS:
        raise PngError("unknown colour type %d" % ctype)
    if ctype in (0, 4):
        raise PngError("greyscale PNG - a normal map needs red, green and blue")
    if ctype == 3:
        raise PngError("palette PNG is not supported; save the normal map as RGB")
    if depth not in (8, 16):
        raise PngError("bit depth %d is not supported (8 or 16 only)" % depth)
    if interlace:
        raise PngError("Adam7-interlaced PNGs are not supported; re-save without interlacing")
    ch = CHANNELS[ctype]
    bpp = ch * (2 if depth == 16 else 1)
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise PngError("corrupt image data (%s)" % e)
    if len(raw) < (stride + 1) * height:
        raise PngError("image data is shorter than the header says")
    maxval = 65535 if depth == 16 else 255

    def rows():
        prev = bytearray(stride)
        o = 0
        for _ in range(height):
            ft = raw[o]
            o += 1
            line = bytearray(raw[o:o + stride])
            o += stride
            if ft == 1:
                for x in range(bpp, stride):
                    line[x] = (line[x] + line[x - bpp]) & 0xFF
            elif ft == 2:
                for x in range(stride):
                    line[x] = (line[x] + prev[x]) & 0xFF
            elif ft == 3:
                for x in range(stride):
                    left = line[x - bpp] if x >= bpp else 0
                    line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
            elif ft == 4:
                for x in range(stride):
                    left = line[x - bpp] if x >= bpp else 0
                    upleft = prev[x - bpp] if x >= bpp else 0
                    line[x] = (line[x] + _paeth(left, prev[x], upleft)) & 0xFF
            elif ft != 0:
                raise PngError("unknown row filter %d" % ft)
            if depth == 16:
                yield [(line[k] << 8) | line[k + 1] for k in range(0, stride, 2)]
            else:
                yield list(line)
            prev = line

    return width, height, ch, maxval, rows()


# ---------------------------------------------------------------- measuring

class Stats(object):
    __slots__ = ("width", "height", "pixels", "valid", "pairs", "s_ab", "s_aa", "s_bb", "s_ab2")

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.pixels = 0
        self.valid = 0
        self.pairs = 0
        self.s_ab = 0.0
        self.s_aa = 0.0
        self.s_bb = 0.0
        self.s_ab2 = 0.0


def _decode_row(row, width, channels, maxval):
    """One row of samples -> (p, t, ok): p = -nx/nz (across-slope), t = +ny/nz (green as Y+)."""
    scale = 2.0 / maxval
    p = [0.0] * width
    t = [0.0] * width
    ok = [False] * width
    for x in range(width):
        k = x * channels
        nx = row[k] * scale - 1.0
        ny = row[k + 1] * scale - 1.0
        nz = row[k + 2] * scale - 1.0
        if row[k + 2] == 0:
            # Two-channel maps leave blue empty (exactly 0); rebuild it from unit length.
            # Only an empty blue is rebuilt - a colour texture must not decode as a normal map.
            r2 = 1.0 - nx * nx - ny * ny
            nz = math.sqrt(r2) if r2 > 0.0 else 0.0
        if nz >= NZ_FLOOR:
            p[x] = -nx / nz
            t[x] = ny / nz
            ok[x] = True
    return p, t, ok


def measure(width, height, channels, maxval, rows):
    """Accumulate the mixed-derivative sums over every interior pixel."""
    st = Stats(width, height)
    older = None      # row y-1
    middle = None     # row y
    for row in rows:
        cur = _decode_row(row, width, channels, maxval)   # row y+1
        st.pixels += width
        st.valid += sum(cur[2])
        if older is not None:
            p_up, _t_up, ok_up = older
            _p_mid, t_mid, ok_mid = middle
            p_dn, _t_dn, ok_dn = cur
            for x in range(1, width - 1):
                if ok_up[x] and ok_dn[x] and ok_mid[x - 1] and ok_mid[x + 1]:
                    a = p_dn[x] - p_up[x]
                    b = t_mid[x + 1] - t_mid[x - 1]
                    ab = a * b
                    st.s_ab += ab
                    st.s_aa += a * a
                    st.s_bb += b * b
                    st.s_ab2 += ab * ab
                    st.pairs += 1
        older, middle = middle, cur
    return st


def verdict(st):
    """(verdict, agreement, z, reason). agreement > 0 means green reads as Y+."""
    if st.pixels == 0 or st.valid < MIN_VALID * st.pixels:
        return (UNDECIDED, 0.0, 0.0,
                "most pixels do not decode to an upward-facing normal - is this a tangent-space normal map?")
    if st.pairs < MIN_PAIRS:
        return UNDECIDED, 0.0, 0.0, "image too small"
    if st.s_aa == 0.0 or st.s_bb == 0.0 or st.s_ab2 == 0.0:
        return (UNDECIDED, 0.0, 0.0,
                "no relief that bends both ways (flat, or it varies along one axis only)")
    agreement = st.s_ab / math.sqrt(st.s_aa * st.s_bb)
    z = st.s_ab / math.sqrt(st.s_ab2)
    if abs(z) < MIN_Z:
        return UNDECIDED, agreement, z, "relief too faint to tell from 8-bit rounding"
    if abs(agreement) < MIN_AGREEMENT:
        return UNDECIDED, agreement, z, "both readings of green fit about equally badly"
    return (Y_PLUS if agreement > 0 else Y_MINUS), agreement, z, ""


def curl(st):
    """Leftover curl under each reading, as a share of the total (0 = a perfect slope field)."""
    total = st.s_aa + st.s_bb
    if total == 0.0:
        return 0.0, 0.0
    return (total - 2.0 * st.s_ab) / total, (total + 2.0 * st.s_ab) / total


def check_file(path):
    w, h, ch, mx, rows = read_png(path)
    st = measure(w, h, ch, mx, rows)
    v, agreement, z, reason = verdict(st)
    c_plus, c_minus = curl(st)
    return {"path": path, "verdict": v, "agreement": agreement, "z": z,
            "curl_yplus": c_plus, "curl_yminus": c_minus,
            "pairs": st.pairs, "size": "%dx%d" % (w, h), "reason": reason}


# ---------------------------------------------------------------- command line

def collect(paths):
    out = []
    seen = set()
    for p in paths:
        if os.path.isdir(p):
            found = []
            for root, _dirs, files in os.walk(p):
                for name in files:
                    if name.lower().endswith(".png"):
                        found.append(os.path.join(root, name))
            items = sorted(found)
        else:
            items = [p]
        for f in items:
            key = os.path.normcase(os.path.abspath(f))
            if key not in seen:
                seen.add(key)
                out.append(f)
    return out


def _say(text):
    sys.stdout.write(text + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Decide from the pixels whether a normal map is Y+ (OpenGL) or Y- (DirectX).")
    ap.add_argument("paths", nargs="+", help="PNG files or folders (searched recursively)")
    ap.add_argument("--expect", choices=["y+", "y-"],
                    help="exit 1 if any map is decided the other way")
    ap.add_argument("--tsv", action="store_true", help="tab-separated output")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    files = collect(args.paths)
    if not files:
        _say("no PNG files found")
        return 2

    results = []
    unreadable = 0
    if args.tsv:
        _say("verdict\tagreement\tz\tcurl_yplus\tcurl_yminus\tpairs\tsize\treason\tpath")
    for f in files:
        try:
            r = check_file(f)
        except (PngError, OSError) as e:
            unreadable += 1
            if args.tsv:
                _say("unreadable\t\t\t\t\t\t\t%s\t%s" % (e, f))
            else:
                _say("%-10s %s  (%s)" % ("unreadable", f, e))
            continue
        results.append(r)
        if args.tsv:
            _say("%s\t%+.4f\t%.1f\t%.4f\t%.4f\t%d\t%s\t%s\t%s" % (
                r["verdict"], r["agreement"], r["z"], r["curl_yplus"], r["curl_yminus"],
                r["pairs"], r["size"], r["reason"], f))
        else:
            tail = "  (%s)" % r["reason"] if r["reason"] else ""
            _say("%-10s %s  agreement %+.3f  z %.1f  curl if Y+ %.3f / if Y- %.3f%s" % (
                r["verdict"], f, r["agreement"], r["z"], r["curl_yplus"], r["curl_yminus"], tail))

    n_plus = sum(1 for r in results if r["verdict"] == Y_PLUS)
    n_minus = sum(1 for r in results if r["verdict"] == Y_MINUS)
    n_und = sum(1 for r in results if r["verdict"] == UNDECIDED)
    summary = "%d file(s): Y+ %d, Y- %d, undecided %d, unreadable %d" % (
        len(files), n_plus, n_minus, n_und, unreadable)

    code = 0
    if args.expect:
        want = Y_PLUS if args.expect == "y+" else Y_MINUS
        wrong = [r for r in results if r["verdict"] not in (want, UNDECIDED)]
        summary += "  |  expected %s: %d match, %d CONTRADICT, %d not checked" % (
            want, n_plus if want == Y_PLUS else n_minus, len(wrong), n_und)
        if wrong:
            code = 1
        elif n_plus + n_minus == 0:
            code = 3
    if unreadable:
        code = 2 if code in (0, 3) else code
    if not args.tsv:
        _say("")
    _say(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
