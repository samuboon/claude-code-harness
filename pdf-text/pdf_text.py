# -*- coding: utf-8 -*-
"""pdf-text - take the text out of a PDF with nothing but the standard library,
and when that is not possible, say which PDF and which font by name.

    python pdf_text.py contract.pdf -o contract.txt
    python pdf_text.py scanned.pdf  -o out.txt      # exit 2, names the reason
    python pdf_text.py contract.pdf -o out.txt --json

The failure this is built around is not "the PDF could not be read." It is a PDF that
could not be read returning an empty string, or a number with a digit missing, to something
that will quote it. A scanned page and a page of text are the same object to the caller:
both parse, both have pages, and one of them has no characters in it anywhere. If the
reader answers that with `""` then the difference between "this document says nothing"
and "this document is a photograph" has been thrown away at the one place it was visible.

So every path out of here is named. A page image with no text operators is reported as an
image-only PDF, with the number of images. A font with no /ToUnicode CMap is reported with
its BaseFont name, because its glyph codes are a private numbering that no table can
undo. A character that was reached but not decoded is written into the output as U+FFFD
and counted, so a number that lost a digit looks wrong instead of looking smaller.

Standard library only (`zlib`, `re`). No network, no poppler, no pdfminer, no wheel to
install - which is the whole reason it exists: the environments where a PDF has to be read
are often the environments where nothing can be installed.

Output goes to a **file, written UTF-8**, never to stdout by default. On a cp932 console
`print(japanese_text)` raises UnicodeEncodeError and the extraction is lost after the work
was already done. `--stdout` is there if you want it, and it reconfigures the stream first.
Everything this prints about itself - every report line, every font name - is forced to
ASCII for the same reason.

Exit 0 = text extracted, undecoded characters at or under --max-missing.
Exit 1 = text extracted but too many characters could not be decoded; the fonts are named.
Exit 2 = no text could be taken out of this PDF; the reason is named.
Exit 3 = the extraction did not happen (no such file, not a PDF, bad arguments).
"""
import argparse
import json
import re
import sys
import zlib

MISSING = "�"

# Filters we can undo here. Anything else is named rather than guessed at.
SUPPORTED_FILTERS = ("FlateDecode", "ASCIIHexDecode")
# Filters that only ever wrap image data - their presence is not a text problem.
IMAGE_FILTERS = ("DCTDecode", "JPXDecode", "CCITTFaxDecode", "JBIG2Decode")

SIMPLE_SUBTYPES = (b"/TrueType", b"/Type1", b"/MMType1", b"/Type3")


# ---------------------------------------------------------------- object layer

def get_objects(data):
    """{object number -> body bytes} for every `N G obj ... endobj` in the file."""
    objs = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        num = int(m.group(1))
        start = m.end()
        end = data.find(b"endobj", start)
        if end < 0:
            continue
        objs[num] = data[start:end]
    return objs


def filters_of(body):
    """Filter names declared in a stream dictionary, in order."""
    head = body.split(b"stream", 1)[0]
    return [f.decode("ascii") for f in re.findall(rb"/([A-Za-z0-9]+Decode)\b", head)]


def stream_of(body, unsupported=None):
    """Decoded stream bytes, or None. Unsupported filters are recorded, not guessed."""
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None
    raw = body[m.end():body.find(b"endstream", m.end())]
    names = filters_of(body)
    for name in names:
        if name in IMAGE_FILTERS:
            return None
        if name not in SUPPORTED_FILTERS:
            if unsupported is not None:
                unsupported.add(name)
            return None
    for name in names:
        if name == "ASCIIHexDecode":
            hx = re.sub(rb"[^0-9A-Fa-f]", b"", raw.split(b">", 1)[0])
            if len(hx) % 2:
                hx += b"0"
            raw = bytes.fromhex(hx.decode("ascii"))
        elif name == "FlateDecode":
            try:
                raw = zlib.decompress(raw)
            except Exception:
                try:
                    # Truncated or slightly malformed streams are common and still
                    # mostly readable; take what inflates and keep going.
                    raw = zlib.decompressobj().decompress(raw)
                except Exception:
                    return None
    return raw


def expand_objstm(objs, unsupported=None):
    """PDF 1.5+ folds most objects into /ObjStm streams. Unfold them into objs."""
    added = {}
    for body in list(objs.values()):
        if b"/ObjStm" not in body:
            continue
        st = stream_of(body, unsupported)
        if not st:
            continue
        mn = re.search(rb"/N\s+(\d+)", body)
        mf = re.search(rb"/First\s+(\d+)", body)
        if not (mn and mf):
            continue
        count, first = int(mn.group(1)), int(mf.group(1))
        pairs = re.findall(rb"(\d+)\s+(\d+)", st[:first])[:count]
        for i, (num, off) in enumerate(pairs):
            start = first + int(off)
            end = first + int(pairs[i + 1][1]) if i + 1 < len(pairs) else len(st)
            added[int(num)] = st[start:end]
    for num, body in added.items():
        objs.setdefault(num, body)
    return objs


# ------------------------------------------------------------------ font layer

def hexstr_to_text(h):
    h = h.decode("ascii")
    if len(h) % 4 == 0:
        try:
            return bytes.fromhex(h).decode("utf-16-be", "replace")
        except Exception:
            return ""
    try:
        return chr(int(h, 16))
    except Exception:
        return ""


def parse_tounicode(cmap):
    """A /ToUnicode CMap is the only thing that makes a subset font readable.
    Returns {code -> text}."""
    table = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cmap, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            table[int(src, 16)] = hexstr_to_text(dst)
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cmap, re.S):
        for lo, hi, dst in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            lo_i, hi_i, base = int(lo, 16), int(hi, 16), int(dst, 16)
            for i in range(lo_i, min(hi_i, lo_i + 65535) + 1):
                try:
                    table[i] = chr(base + (i - lo_i))
                except Exception:
                    pass
        for lo, _hi, arr in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S):
            lo_i = int(lo, 16)
            for k, item in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", arr)):
                table[lo_i + k] = hexstr_to_text(item)
    return table


def winansi_table():
    """WinAnsiEncoding is cp1252. Positions cp1252 refuses are left out on purpose."""
    t = {}
    for b in range(32, 256):
        try:
            t[b] = bytes([b]).decode("cp1252")
        except Exception:
            continue
    return t


WINANSI = winansi_table()

# /Differences names glyphs, not characters. Digits and punctuation are the ones that
# matter: a missing digit changes a number, a missing letter is visible as a typo.
GLYPH_NAMES = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "comma": ",", "period": ".", "percent": "%", "hyphen": "-", "endash": "–",
    "parenleft": "(", "parenright": ")", "space": " ", "colon": ":",
    "semicolon": ";", "slash": "/", "yen": "¥", "dollar": "$", "sterling": "£",
    "plus": "+", "equal": "=", "asterisk": "*", "quotesingle": "'", "quotedbl": '"',
}


def parse_differences(body, objs):
    """/Encoding << /Differences [...] >> -> {code -> text}, or None."""
    m = re.search(rb"/Encoding\s+(\d+)\s+\d+\s+R", body)
    enc = objs.get(int(m.group(1))) if m else None
    src = enc if enc is not None else body
    d = re.search(rb"/Differences\s*\[(.*?)\]", src, re.S)
    if not d:
        return None
    table, code = {}, 0
    for tok in re.finditer(rb"(\d+)|/([^\s/\[\]]+)", d.group(1)):
        if tok.group(1):
            code = int(tok.group(1))
            continue
        name = tok.group(2).decode("latin-1")
        ch = GLYPH_NAMES.get(name)
        if ch is None and re.fullmatch(r"uni[0-9A-Fa-f]{4}", name):
            ch = chr(int(name[3:], 16))
        if ch is not None:
            table[code] = ch
        code += 1
    return table or None


def basefont_of(body):
    m = re.search(rb"/BaseFont\s*/([^\s/\[\]<>]+)", body)
    return m.group(1).decode("latin-1") if m else "(unnamed)"


def subtype_of(body):
    m = re.search(rb"/Subtype\s*/([A-Za-z0-9]+)", body)
    return m.group(1).decode("latin-1") if m else "(none)"


def build_font(num, body, objs, unsupported):
    """Everything known about one font object, decodable or not."""
    info = {
        "object": num,
        "basefont": basefont_of(body),
        "subtype": subtype_of(body),
        "tounicode": False,
        "decodable": False,
        "two_byte": b"/Type0" in body or b"Identity" in body,
        "reason": None,
        "table": None,
    }
    m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
    if m and int(m.group(1)) in objs:
        info["tounicode"] = True
        cmap = stream_of(objs[int(m.group(1))], unsupported)
        if cmap:
            table = parse_tounicode(cmap)
            if table:
                info["decodable"], info["table"] = True, table
                return info
            info["reason"] = "its /ToUnicode CMap contains no bfchar or bfrange entries"
            return info
        info["reason"] = "its /ToUnicode stream could not be decompressed"
        return info

    if info["two_byte"]:
        # A composite font addressed by glyph index with no /ToUnicode is a private
        # numbering. There is no table anywhere that turns it back into characters.
        info["reason"] = ("it is a composite (Type0) font with no /ToUnicode CMap, so its "
                          "codes are glyph indexes into a subset with no character meaning")
        return info

    if any(st in body for st in SIMPLE_SUBTYPES):
        table = dict(WINANSI)
        diff = parse_differences(body, objs)
        if diff:
            table.update(diff)
        info["decodable"], info["table"], info["two_byte"] = True, table, False
        return info

    info["reason"] = "it has no /ToUnicode CMap and no simple-font encoding to fall back on"
    return info


# --------------------------------------------------------------- content layer

def unescape(b):
    """PDF literal-string escapes, including the three-digit octal form."""
    out = bytearray()
    i = 0
    simple = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
    while i < len(b):
        c = b[i]
        if c == 0x5C and i + 1 < len(b):
            n = b[i + 1]
            if n in simple:
                out.append(simple[n])
                i += 2
                continue
            if 0x30 <= n <= 0x37:
                j, digits = i + 1, b""
                while j < len(b) and len(digits) < 3 and 0x30 <= b[j] <= 0x37:
                    digits += bytes([b[j]])
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            out.append(n)
            i += 2
            continue
        out.append(c)
        i += 1
    return bytes(out)


def decode_show(codes, table, two_byte, stats):
    """Codes to text. A code the table does not have becomes one U+FFFD - never nothing.

    Dropping it instead is what turns 3,200 into 320 with no sign that anything happened,
    and a number with a digit gone is worse than no number.
    """
    out = []
    if two_byte:
        for i in range(0, len(codes) - 1, 2):
            ch = table.get((codes[i] << 8) | codes[i + 1]) or MISSING
            out.append(ch)
        if len(codes) % 2:
            out.append(MISSING)
    else:
        for b in codes:
            ch = table.get(b)
            if not ch:
                ch = chr(b) if 32 <= b < 127 else MISSING
            out.append(ch)
    stats["total"] += len(out)
    stats["missing"] += sum(1 for c in out if c == MISSING)
    return "".join(out)


SHOW = re.compile(
    rb"/([^\s/\[\]<>]+)\s+[\d.]+\s+Tf"
    rb"|\((?:[^()\\]|\\.)*\)\s*Tj"
    rb"|<([0-9A-Fa-f\s]+)>\s*Tj"
    rb"|\[(.*?)\]\s*TJ"
    rb"|\bTD\b|\bTd\b|\bT\*\b|\bET\b",
    re.S)
IN_ARRAY = re.compile(rb"\((?:[^()\\]|\\.)*\)|<([0-9A-Fa-f\s]+)>", re.S)


def hex_codes(raw):
    hx = re.sub(rb"\s", b"", raw)
    if len(hx) % 2:
        hx += b"0"
    return bytes.fromhex(hx.decode("ascii"))


# ------------------------------------------------------------------ the reader

def read(path, max_missing=0.02):
    """Extract text and, more importantly, an account of what could not be extracted."""
    with open(path, "rb") as fh:
        data = fh.read()

    result = {
        "path": str(path),
        "status": "unreadable",
        "text": "",
        "chars": 0,
        "missing": 0,
        "missing_ratio": 0.0,
        "text_operators": 0,
        "images": 0,
        "pages": 0,
        "fonts": [],
        "unsupported_filters": [],
        "reasons": [],
    }

    if not data[:1024].lstrip().startswith(b"%PDF-"):
        result["reasons"].append("this file does not start with %PDF-; it is not a PDF")
        return result

    unsupported = set()
    objs = expand_objstm(get_objects(data), unsupported)

    if re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data):
        result["reasons"].append(
            "the PDF is encrypted (/Encrypt in the trailer). Decryption is not implemented "
            "here; remove the protection with the tool that applied it, then run this again")
        return result
    if not objs:
        result["reasons"].append(
            "no PDF objects were found. The file is truncated, or it is a linearized "
            "cross-reference stream this reader does not follow")
        return result

    result["pages"] = len(re.findall(rb"/Type\s*/Page\b", data))
    result["images"] = sum(1 for b in objs.values() if re.search(rb"/Subtype\s*/Image\b", b))

    font_objs = {}
    for num, body in objs.items():
        if re.search(rb"/Type\s*/Font\b", body) or (b"/BaseFont" in body and b"/Widths" in body):
            font_objs[num] = build_font(num, body, objs, unsupported)

    # Resource name (/F1) -> font object. Descendant fonts are reached through the parent,
    # so a name can land on a Type0 wrapper; that wrapper is the one that carries /ToUnicode.
    name_to_font = {}
    for body in objs.values():
        for name, num in re.findall(rb"/([^\s/\[\]<>]+)\s+(\d+)\s+\d+\s+R", body):
            if int(num) in font_objs:
                name_to_font[name] = int(num)

    stats = {"total": 0, "missing": 0}
    used = set()
    pieces = []
    for body in objs.values():
        if b"/Contents" in body and re.search(rb"/Type\s*/Page\b", body):
            continue  # a page dictionary, not its content stream
        stream = stream_of(body, unsupported)
        if not stream or (b"Tj" not in stream and b"TJ" not in stream):
            continue
        current = None
        for m in SHOW.finditer(stream):
            tok = m.group(0)
            if tok.endswith(b"Tf"):
                num = name_to_font.get(m.group(1))
                current = font_objs.get(num)
                if current is not None:
                    used.add(num)
                elif m.group(1):
                    result.setdefault("_unresolved", set()).add(m.group(1).decode("latin-1"))
                continue
            if tok in (b"TD", b"Td", b"T*", b"ET"):
                pieces.append("\n")
                continue
            if current is not None and current["decodable"]:
                table, two = current["table"], current["two_byte"]
            else:
                table, two = {}, bool(current and current["two_byte"])
            if tok.endswith(b"Tj") or tok.endswith(b"TJ"):
                result["text_operators"] += 1
            if m.group(2):
                pieces.append(decode_show(hex_codes(m.group(2)), table, two, stats))
            elif m.group(3) is not None:
                for sm in IN_ARRAY.finditer(m.group(3)):
                    if sm.group(1):
                        pieces.append(decode_show(hex_codes(sm.group(1)), table, two, stats))
                    else:
                        pieces.append(decode_show(unescape(sm.group(0)[1:-1]), table, two, stats))
            elif tok.startswith(b"("):
                pieces.append(decode_show(unescape(tok[1:tok.rfind(b")")]), table, two, stats))

    text = re.sub(r"\n{2,}", "\n", "".join(pieces))
    result["text"] = text
    result["chars"] = stats["total"]
    result["missing"] = stats["missing"]
    result["missing_ratio"] = (stats["missing"] / stats["total"]) if stats["total"] else 0.0
    result["unsupported_filters"] = sorted(unsupported)
    result["fonts"] = [
        {k: v for k, v in f.items() if k != "table"}
        for num, f in sorted(font_objs.items()) if num in used
    ]

    broken = [f for f in result["fonts"] if not f["decodable"]]
    unresolved = sorted(result.pop("_unresolved", set()))

    if stats["total"] == 0:
        if result["text_operators"] == 0 and result["images"]:
            result["reasons"].append(
                "this PDF has %d image%s and no text-drawing operators at all: the pages are "
                "pictures. Text can only come out of it through OCR, which is not done here"
                % (result["images"], "" if result["images"] == 1 else "s"))
        elif result["text_operators"] == 0:
            result["reasons"].append(
                "no text-drawing operators (Tj/TJ) were found in any content stream")
        else:
            result["reasons"].append(
                "text-drawing operators were found but produced no characters")
    elif stats["missing"] == stats["total"]:
        result["reasons"].append(
            "every character position was reached and none of them could be decoded")
    elif result["missing_ratio"] > max_missing:
        result["status"] = "partial"
        result["reasons"].append(
            "%.1f%% of the characters could not be decoded (%d of %d). They are U+FFFD in the "
            "output; any number on a line containing one may have lost a digit"
            % (100 * result["missing_ratio"], stats["missing"], stats["total"]))
    else:
        result["status"] = "ok"

    for f in broken:
        result["reasons"].append(
            "font %s (object %d, /%s) could not be decoded: %s"
            % (f["basefont"], f["object"], f["subtype"], f["reason"]))
    for name in unresolved:
        result["reasons"].append(
            "content referred to font /%s, which is not a font object this reader found; "
            "every character drawn with it is U+FFFD" % name)
    for name in result["unsupported_filters"]:
        result["reasons"].append(
            "a stream uses the %s filter, which is not implemented here; whatever it held "
            "is missing from the output" % name)
    return result


# -------------------------------------------------------------------- the edge

def ascii_only(s):
    """Everything this prints about itself survives a cp932 console. A report that dies
    on its own punctuation is worse than no report - the work is done and thrown away."""
    return s.encode("ascii", "backslashreplace").decode("ascii")


def report(result, out_path):
    lines = ["file        %s" % ascii_only(result["path"]),
             "status      %s" % result["status"],
             "pages       %d" % result["pages"],
             "characters  %d (%d undecoded, %.1f%%)"
             % (result["chars"], result["missing"], 100 * result["missing_ratio"])]
    if result["images"]:
        lines.append("images      %d" % result["images"])
    if out_path:
        lines.append("written     %s (UTF-8)" % ascii_only(str(out_path)))
    for r in result["reasons"]:
        lines.append("")
        lines.append(ascii_only(r))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="pdf_text.py",
        description="Extract text from a PDF with the standard library only, "
                    "and name the reason when it cannot be done.")
    p.add_argument("pdf")
    p.add_argument("-o", "--out", help="output file (UTF-8). Default: <pdf name>.txt")
    p.add_argument("--stdout", action="store_true",
                   help="also write the text to stdout (reconfigured to UTF-8 first)")
    p.add_argument("--json", action="store_true",
                   help="print the report as JSON on stdout instead of text on stderr")
    p.add_argument("--max-missing", type=float, default=2.0, metavar="PCT",
                   help="undecoded characters allowed before exit 1 (default 2.0%%)")
    args = p.parse_args(argv)

    try:
        result = read(args.pdf, max_missing=args.max_missing / 100.0)
    except FileNotFoundError:
        sys.stderr.write("no such file: %s\n" % ascii_only(args.pdf))
        return 3
    except OSError as e:
        sys.stderr.write("could not read %s: %s\n" % (ascii_only(args.pdf), ascii_only(str(e))))
        return 3

    out_path = None
    if result["text"]:
        out_path = args.out or (re.sub(r"\.pdf$", "", args.pdf, flags=re.I) + ".txt")
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(result["text"])
        except OSError as e:
            # The text was extracted and is about to be lost. Say where it was going.
            sys.stderr.write("could not write %s: %s\n"
                             % (ascii_only(str(out_path)), ascii_only(str(e))))
            return 3

    if args.json:
        payload = {k: v for k, v in result.items() if k != "text"}
        payload["out"] = str(out_path) if out_path else None
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        sys.stderr.write(report(result, out_path) + "\n")

    if args.stdout and result["text"]:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(result["text"])

    return {"ok": 0, "partial": 1, "unreadable": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
