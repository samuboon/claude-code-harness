**日本語版: [README.ja.md](README.ja.md)**

# vrc-texture-audit — the alpha channel nobody uses costs you half the texture

An avatar texture saved as RGBA where every single pixel is opaque compresses to BC3 instead of BC1. Same picture, **twice the VRAM**. Unity will not tell you, because as far as Unity is concerned you asked for an alpha channel and you got one.

This walks a folder, reads the headers, **actually decodes the alpha plane of every PNG**, and names the files whose alpha is dead weight.

```
$ python3 vrc_texture_audit.py ./Assets/MyAvatar --platform both

file                     fmt         size  alpha         est
Body/body_basecolor.png  png    4096x4096  UNUSED     21.33M
Body/body_normal.png     png    2048x2048  UNUSED      5.33M
Hair/hair_basecolor.png  png    2048x2048  yes         5.33M
Hair/hair_mask.png       png    1024x1024  UNUSED      1.33M
Hair/hair_mask_copy.png  png    1024x1024  UNUSED      1.33M
Body/eye_1000x600.png    png     1000x600  yes         0.76M *

6 textures, 35.43 MB estimated (1.2s)
  PC    -> Excellent (Excellent band is <= 40 MB; VRChat's own thresholds, read 2026-09-15)
  QUEST -> Poor (Poor band is <= 40 MB; VRChat's own thresholds, read 2026-09-15)

findings:
  [alpha not used] 4 texture(s) carry an alpha channel in which every pixel is opaque.
                   dropping the alpha frees an estimated 14.67 MB:
                     Body/body_basecolor.png (4096x4096, -10.67 MB)
                     ...
  [duplicate] 1 group(s) of byte-identical files, est 1.33 MB shipped twice:
                Hair/hair_mask.png == Hair/hair_mask_copy.png
  [not power of two] 1 texture(s), marked * above
```

**No Unity. No Blender. No pip install.** One file, Python 3.8+, standard library only, no network access. **59 tests, 28 deliberate mutations, all caught.**

---

## Use

```bash
python3 vrc_texture_audit.py ./Assets/MyAvatar
python3 vrc_texture_audit.py ./Assets/MyAvatar --platform quest --format md   # paste into an issue
python3 vrc_texture_audit.py ./Assets/MyAvatar --max-mb 40                    # exit 1 if over
```

| Option | Default | |
|---|---|---|
| `--platform` | `pc` | `pc` / `quest` / `both`. |
| `--format` | `text` | `text` / `tsv` (spreadsheet) / `md` (issue or pull request). |
| `--top` | `20` | Rows shown, largest first. `0` shows all. |
| `--max-mb` | *(off)* | Exit **1** if the estimate is over this. For CI. |
| `--no-alpha-scan` | off | Headers only. Much faster, and the main finding disappears. |
| `--max-scan-pixels` | `67108864` | Skip the alpha decode above this size instead of hanging. Skipped files are marked, not counted as opaque. |

Exit codes: **0** scanned / **1** over `--max-mb` / **2** nothing was read (a mistyped path must not print a clean report).

Reads `.png` `.jpg` `.tga` `.bmp` `.psd` `.gif`. The alpha *decode* is PNG only; for the rest, the presence of an alpha channel is read from the header.

---

## The three things it finds

**1. Alpha channels in which every pixel is opaque.** This is the one worth running for. The check is not "is there an alpha channel" — every exporter writes one — but "is any pixel in it not 255". Palette PNGs are answered from `tRNS` alone; RGBA and grey+alpha are decoded.

**2. Byte-identical duplicates.** The same mask exported twice under two names is shipped twice.

**3. Sizes that are not a power of two.** Marked `*`. They do not block compression, but they are usually an export accident.

## Why the numbers are what they are

| Quantity | Where it comes from |
|---|---|
| Texture Memory thresholds | VRChat's own documentation, [Avatar Performance Ranking System](https://docs.vrchat.com/docs/avatar-performance-ranking-system), read 2026-09-15. PC `40 / 75 / 110 / 150` MB, Quest `10 / 18 / 25 / 40` MB, for Excellent / Good / Medium / Poor. Over Poor is Very Poor. The test suite fails if anyone edits these. |
| MB per texture | **Our arithmetic, not VRChat's number.** BC1 = 8 bytes per 4x4 block = 0.5 B/px; BC3 = 16 bytes per block = 1.0 B/px; mipmaps add a factor converging to 4/3. |
| Unknown alpha | Costed **as if present**. An audit that under-reports is worse than one that over-reports. |

## How it decodes a 4096x4096 PNG in pure Python

PNG filtering is byte-wise, and the "left" reference is `bpp` bytes back — the same component of the previous pixel. **So the alpha plane of an RGBA8 image can be unfiltered on its own**, with the other three quarters of the decompressed bytes thrown away. Measured on one 4096x4096 RGBA PNG (Python 3.13.3, 2026-09-15):

| | |
|---|---:|
| Unfiltering all four planes | 2.75 s |
| **Unfiltering the alpha plane only** | **0.90 s** |

It also stops at the first non-opaque byte, so textures that *do* use their alpha are answered almost instantly (2048x2048 with holes: 0.019 s).

---

## What this does not do

Written before anyone can be disappointed by it.

- **The MB is an estimate, not VRChat's number.** VRChat's own figure comes from the built asset bundle. If your import settings differ from the assumption above, so will the number. Use it to compare textures with each other, not to argue with the avatar uploader.
- **It does not read Unity import settings.** `Max Size`, `Compression`, `Crunch`, `Generate Mip Maps`, `sRGB` — none of them. A 4096 source imported at `Max Size 1024` is reported here at its source resolution, which is four times too large.
- **Quest does not use BC at all.** It uses ASTC. The 0.5/1.0 B/px arithmetic is a proxy there, and the Quest ranking line is the weakest thing this tool prints.
- **The alpha decode is PNG only, and not all PNG.** Interlaced files and bit depths other than 8 and 16 are reported as *unknown*, never as "not used". TGA, PSD, BMP and GIF are read from the header only; GIF transparent-index is not inspected at all.
- **It does not know which textures your avatar actually uses.** It walks a folder. Unused files in that folder inflate the total; textures outside it are invisible.
- **"Alpha unused" is not always "delete the alpha".** Shaders read the alpha channel for smoothness, metallic maps and masks, where 255 everywhere is a legitimate value. The tool reports pixels; you decide.
- **Untested against real avatar projects at scale.** The largest tree it has run on is a six-file fixture. It has never been pointed at a folder with a thousand textures.
- **No PSD layer data is read** — only the header's channel count, which is why a PSD with a spot channel can be reported as alpha-bearing.

## Files

| File | |
|---|---|
| `vrc_texture_audit.py` | The tool. One file, no imports beyond the standard library. |
| `test_vrc_texture_audit.py` | 59 tests, including PNG fixtures built by an independently written encoder. `python3 test_vrc_texture_audit.py` |
| `mutation_check.py` | Breaks the tool 28 specific ways and checks the suite notices. `python3 mutation_check.py`. A test suite nobody has seen fail is decoration. The original is restored in a `finally` block. |

Source comments are in Japanese; everything the tool prints is ASCII, because the console this is most likely to run in is a Japanese Windows one.

Part of [claude-code-harness](../README.md). MIT.
