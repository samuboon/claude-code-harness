# -*- coding: utf-8 -*-
"""Build the four demo PDFs in demo/ from scratch, standard library only.

They are written here rather than downloaded so that the demo is reproducible, so that
nothing fetched from the web is committed, and so that the two unreadable ones are
unreadable in a known way:

    text.pdf           simple Type1 font, WinAnsiEncoding      -> reads
    cid-japanese.pdf   Type0/Identity-H with a /ToUnicode CMap -> reads
    scanned.pdf        one image, no text operators            -> exit 2, named
    glyph-ids.pdf      Type0/Identity-H, no /ToUnicode          -> exit 2, named

    python make_demo_pdfs.py [outdir]
"""
import sys
import zlib
from pathlib import Path


def build(objects, root=1):
    """objects: list of bytes bodies, 1-indexed in order. Returns a complete PDF."""
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, root, xref)
    return bytes(out)


def stream(dict_body, payload, compress=True):
    if compress:
        payload = zlib.compress(payload)
        dict_body = dict_body.rstrip()[:-2] + b" /Filter /FlateDecode >>"
    return (dict_body.rstrip()[:-2] + b" /Length %d >>\nstream\n" % len(payload)
            + payload + b"\nendstream")


def page_skeleton(content_obj, resources):
    return [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
        + resources + b" /Contents %d 0 R >>" % content_obj,
    ]


def text_pdf():
    """A plain Type1 font. The digits here are the point of the file: a reader that
    drops undecodable codes turns 3,200 into 320 and nothing says so."""
    content = (b"BT /F1 14 Tf 72 780 Td (Statement of account) Tj\n"
               b"0 -24 Td (Opening balance 3,200 JPY) Tj\n"
               b"0 -24 Td (Platform fee 7.5% of each sale) Tj\n"
               b"0 -24 Td (Closing balance 2,960 JPY) Tj ET\n")
    objs = page_skeleton(4, b"<< /Font << /F1 5 0 R >> >>")
    objs.append(stream(b"<< >>", content))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Encoding /WinAnsiEncoding >>")
    return build(objs)


def cid_japanese_pdf():
    """The case this tool exists for: a subset CID font whose codes mean nothing on their
    own, plus the /ToUnicode CMap that gives them back their characters."""
    text = "契約書　第1条　"  # 契約書 第1条
    text += "本契約は2026年9月23日に発効する。"
    codes = {ch: i + 1 for i, ch in enumerate(dict.fromkeys(text))}
    show = "".join("%04X" % codes[ch] for ch in text)
    cmap = ["/CIDInit /ProcSet findresource begin 12 dict begin begincmap",
            "1 begincodespacerange <0000> <FFFF> endcodespacerange",
            "%d beginbfchar" % len(codes)]
    for ch, code in codes.items():
        cmap.append("<%04X> <%04X>" % (code, ord(ch)))
    cmap += ["endbfchar", "endcmap CMapName currentdict /CMap defineresource pop end end"]
    content = ("BT /F1 16 Tf 72 780 Td <%s> Tj ET\n" % show).encode("ascii")

    objs = page_skeleton(4, b"<< /Font << /F1 5 0 R >> >>")
    objs.append(stream(b"<< >>", content))
    objs.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+KozMinPr6N-Regular "
                b"/Encoding /Identity-H /DescendantFonts [7 0 R] /ToUnicode 6 0 R >>")
    objs.append(stream(b"<< >>", "\n".join(cmap).encode("ascii")))
    objs.append(b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /ABCDEF+KozMinPr6N-Regular "
                b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Japan1) /Supplement 6 >> "
                b"/DW 1000 >>")
    return build(objs)


def scanned_pdf():
    """A page that is a photograph. It parses, it has a page, and there is no text in it
    anywhere - the case where returning "" is a lie."""
    pixels = bytes([0xEE, 0x22, 0xEE, 0x22] * 4)
    objs = page_skeleton(4, b"<< /XObject << /Im0 5 0 R >> >>")
    objs.append(stream(b"<< >>", b"q 400 0 0 300 72 450 cm /Im0 Do Q\n"))
    objs.append(stream(b"<< /Type /XObject /Subtype /Image /Width 4 /Height 4 "
                       b"/ColorSpace /DeviceGray /BitsPerComponent 8 >>", pixels))
    return build(objs)


def glyph_ids_pdf():
    """The same subset font as cid-japanese.pdf with the /ToUnicode CMap taken away.
    The codes are still there and still draw the same page; there is no longer anything
    that says what they are."""
    content = b"BT /F1 16 Tf 72 780 Td <0001000200030004000500060007> Tj ET\n"
    objs = page_skeleton(4, b"<< /Font << /F1 5 0 R >> >>")
    objs.append(stream(b"<< >>", content))
    objs.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+KozMinPr6N-Regular "
                b"/Encoding /Identity-H /DescendantFonts [6 0 R] >>")
    objs.append(b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /ABCDEF+KozMinPr6N-Regular "
                b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Japan1) /Supplement 6 >> "
                b"/DW 1000 >>")
    return build(objs)


DEMOS = {
    "text.pdf": text_pdf,
    "cid-japanese.pdf": cid_japanese_pdf,
    "scanned.pdf": scanned_pdf,
    "glyph-ids.pdf": glyph_ids_pdf,
}


def write_all(outdir, verbose=False):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fn in DEMOS.items():
        path = outdir / name
        path.write_bytes(fn())
        written.append(path)
        if verbose:
            print("wrote %s" % path)
    return written


if __name__ == "__main__":
    write_all(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "demo",
              verbose=True)
