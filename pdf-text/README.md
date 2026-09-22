**日本語: [README.ja.md](README.ja.md)**

# pdf-text — the empty string is the bug

A PDF arrives and something has to read it. On a machine where nothing can be installed —
no poppler, no `pip install`, a locked runner, a container someone else builds — the choice
is between a few hundred lines of standard library and not reading the file at all.

That much is a known problem with known answers. This is about the part after it.

A scanned page and a page of text are the same object to the caller. Both parse, both have
pages, both come back without raising. One of them has no characters in it anywhere. If the
reader answers that with `""`, then **the difference between "this document says nothing"
and "this document is a photograph" has been thrown away at the one place it was visible**,
and what continues downstream is a summary of nothing, or a field left blank, or a number
that was never there.

The same shape, one level down: a subset font with no `/ToUnicode` CMap numbers its glyphs
privately. A reader that drops the codes it cannot map turns **3,200 into 320** and prints
it with no more hesitation than it prints the rest. A wrong number beats a missing number
at every downstream check, because a missing number gets asked about.

So every exit from this tool is named.

```
$ python pdf_text.py demo/scanned.pdf -o out.txt
file        demo/scanned.pdf
status      unreadable
pages       1
characters  0 (0 undecoded, 0.0%)
images      1

this PDF has 1 image and no text-drawing operators at all: the pages are pictures.
Text can only come out of it through OCR, which is not done here
$ echo $?
2
```

```
$ python pdf_text.py demo/glyph-ids.pdf -o out.txt
file        demo/glyph-ids.pdf
status      unreadable
pages       1
characters  7 (7 undecoded, 100.0%)
written     out.txt (UTF-8)

every character position was reached and none of them could be decoded

font ABCDEF+KozMinPr6N-Regular (object 5, /Type0) could not be decoded: it is a
composite (Type0) font with no /ToUnicode CMap, so its codes are glyph indexes into
a subset with no character meaning
$ echo $?
2
```

```
$ python pdf_text.py demo/cid-japanese.pdf -o out.txt
file        demo/cid-japanese.pdf
status      ok
pages       1
characters  28 (0 undecoded, 0.0%)
written     out.txt (UTF-8)
$ echo $?
0
```

Partial reads are partial, not failed: the readable half is written, the undecoded
positions are `U+FFFD` in the file, and the share is on the report with the fonts that
caused it.

```
status      partial
characters  27 (2 undecoded, 7.4%)

7.4% of the characters could not be decoded (2 of 27). They are U+FFFD in the output;
any number on a line containing one may have lost a digit

font XXXXXX+Ghost (object 6, /Type0) could not be decoded: it is a composite (Type0)
font with no /ToUnicode CMap, so its codes are glyph indexes into a subset with no
character meaning
```

Exit **0 = read**, **1 = read with too many undecoded characters** (`--max-missing`,
default 2%), **2 = nothing could be read, the reason is named**, **3 = it did not run**.

---

## What it reads

- Text drawn with `Tj` and `TJ` in `FlateDecode`d or uncompressed content streams
- **CID / composite fonts with a `/ToUnicode` CMap** — the Japanese case, and the reason
  this exists at all. `bfchar`, both `bfrange` forms
- Simple fonts (`/Type1`, `/TrueType`, `/MMType1`, `/Type3`) through WinAnsiEncoding,
  with `/Differences` applied for digits, punctuation and `uniXXXX` names
- PDF 1.5+ files that fold their objects into `/ObjStm` streams
- `ASCIIHexDecode`, and streams with no filter

## What it cannot read — and says so

| Input | What you get |
|---|---|
| Scanned / image-only pages | exit 2, the image count, "text can only come out of it through OCR" |
| Subset font with no `/ToUnicode` | exit 2 (or `partial`), **the BaseFont name**, and why its codes have no character meaning |
| Encrypted PDF (`/Encrypt`) | exit 2, named. No decryption is attempted, with the empty owner password or otherwise |
| `LZWDecode`, `ASCII85Decode`, `RunLengthDecode`, `Crypt` | the filter is named and its stream is left out, rather than guessed at |
| A file that is not a PDF | exit 3, named |
| A code the font's table has no entry for | one `U+FFFD` in the output, counted, never dropped |

It does **not** do OCR, decryption, layout, reading order, columns, tables, forms,
annotations, or word spacing from `TJ` kerning offsets. Line breaks come from `Td`/`TD`/`T*`
and are approximate. **Nothing here reads meaning — it reads characters.** If you need
faithful layout, install a real PDF stack; this is for the machines where you cannot.

## Output is a file, in UTF-8

By default the text goes to `<name>.txt` or to `-o`, written UTF-8, and **not** to stdout.
On a cp932 console `print(japanese_text)` raises `UnicodeEncodeError` — the document is
read, the work is done, and the result dies on the way to the screen. `--stdout` is there
if you want it and reconfigures the stream first.

For the same reason **every line this prints about itself is forced to ASCII**, including
BaseFont names and the file path. A report that falls over on its own punctuation is worse
than no report. (That failure has its own tool here: [`print-codec/`](../print-codec/).)

---

## Measured

**The day this became a tool (2026-09-23).** A vendor's help site answered `403` to us,
while the contract PDF it was refusing to explain was served without complaint. The fields
we needed were in the PDF. The environment had no poppler and no way to add one. The first
draft of this — `zlib`, `re`, and the `Tj` operator — returned the contract, and it was
only when the numbers were checked against the page that the interesting half appeared:
**an earlier version of the same reader had been dropping codes it could not map**, and the
output it produced from a grant document looked entirely normal with digits missing out of
the amounts. Nothing in `""` or in `320` tells you to go and look.

So the rule here is that the reader is allowed to fail and is not allowed to be quiet.
`U+FFFD` is written into the output and counted, `--max-missing` turns a bad ratio into a
non-zero exit, and the two unreadable demos are in the repository precisely so that the
named-failure path is the one that runs on every test run.

**Six deliberate breakages, before the tests were trusted** (2026-09-23). A test suite that
has never been seen to fail is a green light with no bulb in it, so each of these was
introduced into the source on a copy and the suite was run:

| What was broken | Tests that caught it |
|---|---|
| undecodable codes dropped instead of `U+FFFD` | 4 |
| unreadable fonts no longer named | 2 |
| image-only PDFs returned with no reason | 1 |
| output file written cp932 instead of UTF-8 | 2 |
| report not forced to ASCII | 1 |
| `/Encrypt` ignored and read as plain | 1 |

**What is not measured.** The demo PDFs are written by `make_demo_pdfs.py` rather than
collected in the wild, so they are clean examples of each case and not a sample of what
real PDFs do. This has been run against a small number of real documents — Japanese
contracts and a government call for applications — and not against a corpus. Expect
producers whose output is shaped in ways nothing here anticipates.

---

## Files

```
pdf_text.py         the reader and the CLI
test_pdf_text.py    18 tests, standard library only
make_demo_pdfs.py   writes the four demo PDFs from scratch
demo/text.pdf           simple font, digits           -> exit 0
demo/cid-japanese.pdf   CID font + /ToUnicode         -> exit 0
demo/scanned.pdf        one image, no text            -> exit 2, named
demo/glyph-ids.pdf      subset font, no /ToUnicode    -> exit 2, named
```

```
python make_demo_pdfs.py
python -m unittest test_pdf_text -v
```

Python 3.8+. Standard library only. MIT, with the rest of this repository.
