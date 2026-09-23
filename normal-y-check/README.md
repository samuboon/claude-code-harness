1. **Fork** this repository, and in your fork save [`normal-y-check.yml`](normal-y-check.yml) as `.github/workflows/normal-y-check.yml` (Add file → Create new file → paste). No Python on your side.
2. **Actions → normal-y-check → Run workflow**: paste the direct link to the PNG and pick Y+ (OpenGL) or Y− (DirectX).
3. Download the **normal-y-check-result** artifact: the verdict for each map, and a copy with green inverted of every map that pointed the wrong way.

**日本語版: [README.ja.md](README.ja.md)** · [Details on the Actions route](#no-python-run-it-in-your-fork)

# normal-y-check — 10 of the 11 normal maps we gave away were upside down, and nothing in the file said so

A normal map PNG has no field for which way its green channel points. There are two
conventions, and they differ only in that sign: **Y+** (often called "OpenGL") and **Y−**
("DirectX"). Unity's manual puts its side plainly: *"Unity uses Y+ normal maps, sometimes
known as OpenGL format."*
([source](https://docs.unity3d.com/Manual/StandardShaderMaterialParameterNormalMap.html),
read 2026-09-17.) Load a map of the other kind and nothing complains. It imports, it
renders, and every bump lit from above reads as a dent.

**We shipped exactly that.** On 2026-09-13 we put a free pack of fabric textures on BOOTH.
Ten of its eleven normal maps were Y−. We found out four days later, and not by looking at the
maps: we were writing a different tool, checked the sign in its source against Unity's
manual, and noticed the fabric generator had it the other way round. The eleventh map
(a stripe) was fine only by luck — its relief runs in one direction, so its green channel was
a flat 128.

Looking at the maps would not have caught it either. A woven rib rendered as a groove still
looks like fabric. `normal_y_check.py` answers the question from the pixels instead.

```bash
python normal_y_check.py path/to/maps               # one line per PNG
python normal_y_check.py pack/ --expect y+          # exit 1 if any map is decided the other way
python normal_y_check.py pack/ --tsv                # tab-separated, one row per file
```

Standard library only. No engine, no PIL, no install.

---

## No Python: run it in your fork

The workflow [`normal-y-check.yml`](normal-y-check.yml) does the whole thing on GitHub's
runner.

1. **Fork** the repository. In the fork, **Add file → Create new file**, type
   `.github/workflows/normal-y-check.yml` as the name, paste the contents of
   [`normal-y-check.yml`](normal-y-check.yml) and commit. The first time you open **Actions**
   in a fork, GitHub asks you to enable workflows there; that is one click.
2. **Actions → normal-y-check → Run workflow.** Paste the link (up to 20, separated by
   spaces) and pick the convention your engine wants.
3. When the run finishes, its page shows the verdict table, and the **normal-y-check-result**
   artifact holds `report.md`, `verdicts.tsv` and a `fixed/` folder.

For each map the runner does exactly one of three things:

| The map is decided as… | What happens |
|---|---|
| the convention you asked for | nothing; reported as `already Y+` (or `Y-`) |
| the other one | green inverted (`G → max − G`), **checked again**, and the copy put in `fixed/`. Red, blue, alpha, size and bit depth are unchanged. If the copy does not check as what you asked for, it is withheld and the run says so |
| `undecided` | nothing, with the reason. **It is never flipped on a guess** |

Limits: https links only, and it must be the file itself (a `github.com/…/blob/…` page link is
turned into the raw file; other web pages are refused with a note). PNG only, 64 MB per image.
The run fails (red) if any link could not be fetched or read, and still reports the others.

**Where your image goes.** The runner fetches it, checks it and uploads the result. Nothing is
committed to the repository, and the downloaded original is deleted before upload, so the
artifact holds only the fixed copies. The artifact is kept 7 days. **A fork of a public
repository is public**, so anyone can see the run, the links you pasted and the artifact. Use
it for maps you would not mind showing; for the others, run `run_from_urls.py --file your.png`
on your own machine.

**Two things we have not done yet.** The file is not in this repository's own
`.github/workflows/`, because the key we publish with cannot write workflow files (GitHub refused the push); that is
why step 1 has you paste it. And for the same reason **we have not yet watched this workflow
run on GitHub.** What is tested is the script it calls (`run_from_urls.py`, below) and the
workflow file's text (inputs reach the shell only through the environment, the token is
read-only). If the run fails in your fork, the log is the most useful thing you could send us.

---

## How it decides

A tangent-space normal map is a picture of a slope. Red holds the slope across the image,
green the slope down it. Read green with one sign or the other and you get two candidate
slope fields.

**Only one of them can be the slope of an actual surface.** A real slope field has no curl:
walking one pixel down changes the across-slope by the same amount that walking one pixel
across changes the down-slope. With the right sign on green, those two mixed differences
agree pixel by pixel. With the wrong sign they come out equal and opposite. The tool
computes both at every interior pixel and reports which sign they agree with, plus how much
curl is left over under each reading:

```
Y-   Twill_normal.png   agreement -1.000  z -360.6  curl if Y+ 2.000 / if Y- 0.000
```

`curl if Y+` is 0 for a perfect Y+ map and 2 for a perfect Y− map read the wrong way.

This needs relief that bends in both directions at once. **A stripe, a flat map, or pure
noise has none, and for those the answer is `undecided` — with the reason — and never a
guess.** A map is decided only when the agreement is at least 0.25 in size *and* stands at
least 6 standard errors clear of zero.

---

## Measured, on maps whose answer we already knew

| Maps | Result |
|---|---|
| **The fabric pack as we shipped it on 09-13** (11 maps, 512×512) | **10 Y−, 1 undecided** (the stripe) |
| The same pack as fixed on 09-17 | **10 Y+, 1 undecided** (the stripe) |
| Every other normal map our generators produce (65 maps from 10 generators: fabric, floor, metal, liquid, nature, sci-fi, sweets, creature, *washitsu*, knit; 512×512) | **64 Y+, 1 undecided** (the stripe again), **0 Y−** |
| …the same 65 with green inverted | **64 Y−, 1 undecided, 0 Y+** |
| Time | those 65 files in **7.4 s** (about 0.1 s per 512×512 map) |

**No map in any row was given the wrong answer.** The lowest agreement on the shelf was
+0.68 (a brushed-metal map, whose fine streaks push some pixels to the edge of 8-bit range);
everything else was above +0.82.

**The weakest thing about this table is that it is all ours.** Every one of those maps came
out of one routine — central differences, the same derivative the tool itself uses — so of
course they fit. The test suite covers three other ways of making a map (a Sobel filter,
forward differences, and exact analytic normals with no differencing at all), and all three
are decided correctly in both directions. **We have not yet run it on a single map baked in
Substance, Blender, xNormal or a photogrammetry pipeline.** If you do, that row is worth more
than all of the above.

---

## What it cannot do

- **It measures green relative to red.** It assumes red points right (+X), which both
  conventions share. A map with *both* channels inverted reads as Y+. That is a different
  bug, and this tool will not see it.
- **Tangent-space maps only.** Object-space and world-space normal maps are not slope
  pictures, and we have not tested what it says about them. Whatever it prints for one
  means nothing.
- **Relief that varies along one axis only is undecidable**, not just hard: straight
  stripes, a single straight ridge. Turn the same stripes off the axis (the tests use 45°)
  and they become decidable.
- **Hand-painted or heavily edited maps** are not always slope fields. They can come back
  `undecided` because both readings fit badly, which is the correct answer for them.
- **PNG only**, 8 or 16 bits, RGB or RGBA, non-interlaced. A blue channel of exactly 0 is
  treated as empty and rebuilt from unit length (two-channel maps). Maps packed as "AG"
  (X in alpha, as in DXT5nm) are not understood.
- It does not tell you which engine you are in, and it does not fix anything. To fix a Y−
  map for a Y+ engine, invert green: `G → 255 − G`.

---

## The tests

```bash
python -m unittest test_normal_y_check test_run_from_urls -v
python mutation_check.py
```

*Added 2026-09-24 with the Actions route:* `test_run_from_urls.py` has 29 more tests (no
network; fetching is faked), and `mutation_check.py` now also breaks `run_from_urls.py` in 17
ways, the first being "invert the maps that were already right". The first run caught 16 of
17. The survivor was *hand over the inverted copy without checking it again*: with a correct
inverter the re-check never fails, so nothing exercised it. A test now swaps in an inverter
that copies the file unchanged and requires the copy to be withheld. **38 of 38 caught.**
Below is the original record for the checker itself.

**35 tests. `mutation_check.py` breaks the tool on purpose in 21 ways, one line at a time,
and all 21 are caught.** The first of them is the one this tool exists for — swap the
verdict so that agreement means Y− — and it was the first thing we watched fail before
trusting anything else.

**The first run caught 19 of 21.** Both survivors were real gaps in the tests, not
equivalent mutations:

1. *Remove the significance floor.* Nothing noticed, because on 96×96 noise the agreement
   floor alone already held. On an 8×8 patch it does not: with a few dozen pixels, chance
   agreement above 0.25 is easy. A test with 60 small noise patches now requires every one
   to be `undecided`.
2. *Read 16-bit samples on an 8-bit scale.* Nothing noticed, because the ratio `red / blue`
   survives that mistake almost unchanged, so the verdict came out right for the wrong
   reason. What it breaks is the "is this a normal map at all" check. A test now feeds a
   16-bit colour texture and requires the refusal.

The PNG writer in the tests carries its own filters and its own Paeth predictor from RFC 2083,
so breaking the tool's decoder cannot break the encoder the same way (a mistake we made once
before in [`tile-seam/`](../tile-seam/)).

---

## If you run it on your own maps

**The interesting case is the one where it is wrong** — a map you know is Y+ that comes back
Y−, or a well-made map that comes back `undecided`.
[Open an issue](https://github.com/samuboon/claude-code-harness/issues/new) with the
`--tsv` row and where the map came from (which baker, which settings). The row holds numbers
and a file name and no image data.

MIT. Part of [claude-code-harness](https://github.com/samuboon/claude-code-harness).
