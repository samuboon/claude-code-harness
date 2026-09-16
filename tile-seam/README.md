**日本語版: [README.ja.md](README.ja.md)**

# tile-seam — 27 of our own 44 seamless textures fail the seam test everyone writes

A texture is seamless when its right edge continues into its left edge. The obvious way to
check that is to measure the step across the wrap and compare it to a threshold.

**That test is wrong, and we know because we shipped it.** On 2026-09-13 we wrote exactly
that check into a fabric texture generator, and it condemned patterns that were provably
periodic — because a woven rib steps just as far between two ordinary neighbouring columns as
it does across the wrap. The check had no idea which edge was which.

`tile_seam.py` asks a different question:

> **Is the wrap the worst edge in this picture?**

Every adjacent column pair in the image contributes one number. The wrap contributes one
more. If the wrap beats all of them, it is a seam. If it sits inside the distribution, the
pattern is simply that contrasty everywhere and there is nothing wrong with it.

```bash
python tile_seam.py path/to/textures            # 0 = clean, 1 = at least one seam
python tile_seam.py pack/ --tsv                 # one row per file per axis
python tile_seam.py pack/ --naive               # …and what a fixed threshold would have said
```

Standard library only. No Unity, no PIL, no install.

---

## Measured, on textures whose answer we already knew

**44 fabric textures we published for free on BOOTH on 2026-09-13.** They are generated from
pattern functions that are exactly periodic — the generator's own check prints a maximum
periodicity error of `0.000000`. That proves the *functions* are periodic. It does not prove
the PNGs that came out of them are, which is what makes them a fair thing to point this at.

| | Result |
|---|---|
| **tile-seam** | **0 seam, 1 suspect, 43 ok** |
| **A fixed threshold of 8/255 on the raw wrap step** | **28 of 44 called seamed** |
| **…of those, ones tile-seam clears** | **27** — i.e. **61% of our own library**, condemned by the obvious test |
| Time | 44 files of 512×512 in **4.3 s** (120 files in 16.5 s; roughly 0.1 s per image) |

**The one that is not clean is ours too.** `Gingham_Navy_color.png` comes back `suspect` on
both axes: its wrap beats 99% of its own neighbour steps without beating the worst. It is a
false positive — the pattern is exactly periodic. **That is what the `suspect` band costs**,
and it is why `suspect` is a different word from `seam` and does not change the exit code.

**A control, and an honest one.** Pointed at 120 matcap spheres — images that were never
meant to tile — it reports **74 seam, 46 ok**. The 46 are not misses: their background
reaches all four edges, so the largest wrap step among them is **0.1992 of 255**, and 64 of
their 92 axes are **exactly 0**. Those images genuinely do tile. They also show what this
measurement is not: a picture with quiet edges passes no matter what is in the middle of it.

---

## What the output means

```
file                          size       left/right wrap           top/bottom wrap
Stripe_Mono_color.png         512x512    ok      x134.00  97% r    ok      x0.00     0% r
Quilt_normal.png              512x512    ok      x7.48    97% r    ok      x7.48    97% g
Gingham_Navy_color.png        512x512    suspect x64.50   99% r    suspect x64.50   99% r
```

- **`x134.00`** — the wrap step over the *median* neighbour step. Readable, and deliberately
  not what decides anything: `Stripe` is 134× its median and still clean, because a striped
  fabric's median column step is nearly zero and its stripe edges are enormous.
- **`97%`** — the share of that image's own neighbour steps the wrap beats. **This is the
  number that decides.** 100% and it is the worst edge in the picture: `seam`. 99% or more
  without reaching 100%: `suspect`. Below: `ok`.
- **`r`** — the channel that gave the worst answer. Each of R/G/B/alpha is measured on its
  own, so a seam that exists only in the alpha or only in the blue is still found.
- `--strict` moves the `suspect` line from the 99th percentile to the 90th, so you can see
  what is sitting just under it.

---

## What it cannot do

- **PNG only**, non-interlaced. 16-bit files are read at their high byte. JPEG, TGA and PSD
  are skipped with a reason rather than guessed at.
- **It cannot see a seam that is no worse than an edge already in the image.** That is the
  whole design, and it is also the failure mode: put a hard border around a texture and the
  border, not the wrap, becomes the worst edge.
- **The wrap is a mean over the whole boundary.** A seam confined to a narrow band of rows
  gets averaged down by the rows on either side of it.
- **A mirrored texture passes**, because a mirrored texture really is seamless. It does not
  tell you that it is mirrored.
- It says nothing about whether a tile *looks* good, whether the repeat is visible at
  distance, or how to fix anything it finds.

---

## The tests

**68 tests, 21 deliberate mutations, all 21 caught** — but the first run of
`mutation_check.py` caught only 20, and both halves of that are worth writing down:

1. The survivor was breaking the Paeth predictor's tie-break (`pa <= pb` → `pa < pb`). It
   survived because **it is an equivalent mutation**: work the arithmetic through and the two
   forms cannot produce different bytes. It was replaced with one that can.
2. While checking that, we found the test's PNG *encoder* had been calling the tool's own
   `_paeth`. Breaking the predictor broke the encoder identically and the round trip still
   passed — **the test could not have failed**. The encoder now carries a second predictor
   written straight from RFC 2083 §6.6.

```bash
python -m unittest test_tile_seam -v
python mutation_check.py
```

---

## If you run it on a pack you bought

**The interesting case is the one where this is wrong** — a texture that tiles fine and comes
back `seam`, or one with a visible seam that comes back `ok`. There is
[an issue template for it](https://github.com/samuboon/claude-code-harness/issues/new?template=seam-verdict.yml);
paste the `--tsv` row, which contains numbers and a file name and no image data.

We have run this against 164 images, all of which we made ourselves. That is the weakest part
of every number above.

MIT. Part of [claude-code-harness](https://github.com/samuboon/claude-code-harness).
