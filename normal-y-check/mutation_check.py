# -*- coding: utf-8 -*-
"""Break normal_y_check.py and run_from_urls.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker
of this kind plausibly makes; the first one is the whole point of the tool turned upside
down (answer Y+ where the evidence says Y-). The script runs the suite against each mutated
copy and reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

MUTATIONS = [
    ("M1  reverse the verdict: call agreement Y- and disagreement Y+",
     "    return (Y_PLUS if agreement > 0 else Y_MINUS), agreement, z, \"\"",
     "    return (Y_PLUS if agreement < 0 else Y_MINUS), agreement, z, \"\""),
    ("M2  read green with the DirectX sign while calling the result Y+",
     "            t[x] = ny / nz",
     "            t[x] = -ny / nz"),
    ("M3  forget the minus on red, so the across-slope points the wrong way",
     "            p[x] = -nx / nz",
     "            p[x] = nx / nz"),
    ("M4  take the across-slope change along the row instead of down the column",
     "                    a = p_dn[x] - p_up[x]",
     "                    a = middle[0][x + 1] - middle[0][x - 1]"),
    ("M5  guess Y+ when there is no relief that bends both ways",
     "        return (UNDECIDED, 0.0, 0.0,\n                \"no relief that bends both ways",
     "        return (Y_PLUS, 0.0, 0.0,\n                \"no relief that bends both ways"),
    ("M6  drop the significance floor, so noise gets a verdict",
     "    if abs(z) < MIN_Z:",
     "    if False:"),
    ("M7  drop the agreement floor, so rounding alone gets a verdict",
     "    if abs(agreement) < MIN_AGREEMENT:",
     "    if False:"),
    ("M8  report the two curl figures the wrong way round",
     "    return (total - 2.0 * st.s_ab) / total, (total + 2.0 * st.s_ab) / total",
     "    return (total + 2.0 * st.s_ab) / total, (total - 2.0 * st.s_ab) / total"),
    ("M9  accept a colour texture as a normal map",
     "    if st.pixels == 0 or st.valid < MIN_VALID * st.pixels:",
     "    if st.pixels == 0:"),
    ("M10 never rebuild an empty blue channel",
     "        if row[k + 2] == 0:",
     "        if False:"),
    ("M11 rebuild blue for every dark pixel, so a colour texture decodes as a normal map",
     "        if row[k + 2] == 0:",
     "        if nz < NZ_FLOOR:"),
    ("M12 read 16-bit samples as if they were 8-bit",
     "    maxval = 65535 if depth == 16 else 255",
     "    maxval = 255"),
    ("M13 swap the two Paeth fallbacks",
     "    if pb <= pc:\n        return b\n    return c",
     "    if pb <= pc:\n        return c\n    return b"),
    ("M14 drop the left neighbour from the Average filter",
     "                    line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF",
     "                    line[x] = (line[x] + (prev[x] >> 1)) & 0xFF"),
    ("M15 make the Sub filter look one byte back instead of one pixel back",
     "                    line[x] = (line[x] + line[x - bpp]) & 0xFF",
     "                    line[x] = (line[x] + line[x - 1]) & 0xFF"),
    ("M16 exit 0 when a map contradicts --expect",
     "        if wrong:\n            code = 1",
     "        if wrong:\n            code = 0"),
    ("M17 call it a pass when --expect was given and nothing could be decided",
     "        elif n_plus + n_minus == 0:\n            code = 3",
     "        elif n_plus + n_minus == 0:\n            code = 0"),
    ("M18 count an undecided map as a contradiction",
     "        wrong = [r for r in results if r[\"verdict\"] not in (want, UNDECIDED)]",
     "        wrong = [r for r in results if r[\"verdict\"] != want]"),
    ("M19 exit 0 over a file that could not be read",
     "        code = 2 if code in (0, 3) else code",
     "        code = code"),
    ("M20 read the same file twice when it is named twice",
     "            if key not in seen:",
     "            if True:"),
    ("M21 accept a greyscale PNG and read its grey as red",
     "    if ctype in (0, 4):\n        raise PngError",
     "    if False:\n        raise PngError"),
]


# The same for run_from_urls.py, the part the GitHub Actions workflow runs. Its first
# mutation is its whole job turned upside down: invert the maps that were already right.
MUTATIONS_RUN = [
    ("R1  invert the maps that were already the wanted way",
     "    if r[\"verdict\"] == want:\n        res[\"action\"] = \"already \" + want\n    elif r[\"verdict\"] == other:",
     "    if r[\"verdict\"] == other:\n        res[\"action\"] = \"already \" + want\n    elif r[\"verdict\"] == want:"),
    ("R2  flip undecided maps on a guess",
     "    elif r[\"verdict\"] == other:",
     "    elif r[\"verdict\"] != want:"),
    ("R3  invert red instead of green",
     "        for k in range(1, len(row), ch):",
     "        for k in range(0, len(row), ch):"),
    ("R4  write 16-bit maps back as 8-bit",
     "    wide = maxval > 255",
     "    wide = False"),
    ("R5  hand over the inverted file without checking it again",
     "        if again[\"verdict\"] != want:",
     "        if False:"),
    ("R6  fetch plain http links",
     "    if parts.scheme != \"https\":",
     "    if parts.scheme not in (\"https\", \"http\"):"),
    ("R7  keep a user name and password in the link",
     "    if parts.username or parts.password:",
     "    if False:"),
    ("R8  drop the size limit",
     "    if len(data) > limit:",
     "    if False:"),
    ("R9  accept anything that is not a PNG",
     "    if data[:8] != nyc.PNG_SIG:",
     "    if False:"),
    ("R10 exit 0 when an image could not be fetched",
     "    return 1 if bad else 0",
     "    return 0"),
    ("R11 leave the downloaded originals in the result",
     "        for n in os.listdir(work):\n            os.remove(os.path.join(work, n))\n        os.rmdir(work)",
     "        pass"),
    ("R12 let two images with the same name overwrite each other",
     "    while name.lower() in used:",
     "    while False:"),
    ("R13 keep path separators in a file name taken from the link",
     "    base = re.sub(r\"[^A-Za-z0-9._-]+\", \"_\", base).strip(\"._\") or \"image\"",
     "    base = base or \"image\""),
    ("R14 drop the colour-space chunks",
     "        elif tag in KEEP_CHUNKS:",
     "        elif False:"),
    ("R15 copy every chunk, including unknown ones that may describe the old pixels",
     "        elif tag in KEEP_CHUNKS:",
     "        elif tag not in (b\"IDAT\", b\"IEND\"):"),
    ("R16 run past the image limit",
     "    if len(urls) + len(args.file) > MAX_IMAGES:",
     "    if False:"),
    ("R17 fetch a GitHub page link as the web page instead of the raw file",
     "    if m:\n        return",
     "    if False:\n        return"),
]

TARGETS = [("normal_y_check.py", "test_normal_y_check", MUTATIONS),
           ("run_from_urls.py", "test_run_from_urls", MUTATIONS_RUN)]


def run_suite(suite):
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", suite],
                       cwd=str(HERE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode == 0


def main():
    total = 0
    survivors = []
    for fname, suite, mutations in TARGETS:
        src = HERE / fname
        bak = HERE / (fname + ".mutation-backup")
        original = src.read_text(encoding="utf-8")
        if not run_suite(suite):
            print("the unmutated suite %s fails; fix that first" % suite)
            return 2
        shutil.copyfile(str(src), str(bak))
        try:
            for name, old, new in mutations:
                total += 1
                if original.count(old) != 1:
                    print("NOT APPLIED  %s  (target text found %d times)" % (name, original.count(old)))
                    survivors.append(name)
                    continue
                src.write_text(original.replace(old, new), encoding="utf-8")
                caught = not run_suite(suite)
                print("%-8s %s" % ("caught" if caught else "SURVIVED", name))
                if not caught:
                    survivors.append(name)
        finally:
            shutil.copyfile(str(bak), str(src))
            bak.unlink()
    print("\n%d mutations, %d caught, %d survived" % (total, total - len(survivors), len(survivors)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
