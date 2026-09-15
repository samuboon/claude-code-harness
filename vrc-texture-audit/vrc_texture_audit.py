#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VRChat アバターのテクスチャを、Unity を開かずに一括で点検する(標準ライブラリのみ)。

読むのはファイルのヘッダだけ。ただし PNG のアルファだけは実際に画素を展開して、
「アルファ板を持っているのに全画素が不透明」= 無駄に 2 倍の VRAM を食っている板を名指しする。

使い方:
    python vrc_texture_audit.py <フォルダ> [--platform pc|quest|both]
                                [--format text|tsv|md] [--top N]
                                [--no-alpha-scan] [--max-scan-pixels N]
                                [--max-mb N]

戻り値: 0 = 点検した / 1 = --max-mb を超えた / 2 = 1 枚も読めなかった
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import time
import zlib

# --- VRChat の Avatar Performance Ranking の Texture Memory の閾値 -------------
# 逐語の出所: https://docs.vrchat.com/docs/avatar-performance-ranking-system
#   PC    "Texture Memory | 40 MB | 75 MB | 110 MB | 150 MB"
#   Quest "Texture Memory | 10 MB | 18 MB | 25 MB | 40 MB"
#   見出し行はどちらも "Avatar Quality | Excellent | Good | Medium | Poor"
# 到達日 2026-09-15。Poor を超えたものが Very Poor。
# この数字は VRChat のものだが、下の「推定バイト数」はこちらの算術であって
# VRChat が表示する値ではない(README の「できないこと」を読むこと)。
THRESHOLDS = {
    "pc": [("Excellent", 40), ("Good", 75), ("Medium", 110), ("Poor", 150)],
    "quest": [("Excellent", 10), ("Good", 18), ("Medium", 25), ("Poor", 40)],
}
VRC_DOC_URL = "https://docs.vrchat.com/docs/avatar-performance-ranking-system"
VRC_DOC_READ_ON = "2026-09-15"

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".psd", ".gif")

# ブロック圧縮の 1 画素あたりのバイト数。4x4 画素のブロックが
#   BC1(DXT1) = 8 バイト  -> 8 / 16 = 0.5 バイト/画素
#   BC3(DXT5) = 16 バイト -> 16 / 16 = 1.0 バイト/画素
BYTES_PER_PIXEL_NO_ALPHA = 0.5
BYTES_PER_PIXEL_ALPHA = 1.0
# ミップマップは 1 + 1/4 + 1/16 + ... = 4/3 倍に収束する
MIPMAP_FACTOR = 4.0 / 3.0


class Texture:
    """1 枚のテクスチャについて分かったこと。"""

    __slots__ = ("path", "rel", "kind", "width", "height", "alpha", "alpha_used",
                 "note", "digest", "bytes_on_disk", "png_meta")

    def __init__(self, path, rel, kind, width, height, alpha, note=""):
        self.path = path
        self.rel = rel
        self.kind = kind
        self.width = width
        self.height = height
        self.alpha = alpha            # True / False / None(分からない)
        self.alpha_used = None        # True / False / None(調べていない)
        self.note = note
        self.digest = None
        self.bytes_on_disk = 0
        self.png_meta = None

    @property
    def pixels(self):
        return self.width * self.height

    @property
    def est_bytes(self):
        # アルファの有無が分からない形式(GIF 等)は「ある」側に倒す。
        # 予算の点検で外すなら、小さく出るより大きく出るほうが安全なため
        per = BYTES_PER_PIXEL_NO_ALPHA if self.alpha is False else BYTES_PER_PIXEL_ALPHA
        return self.pixels * per * MIPMAP_FACTOR

    @property
    def wasted_bytes(self):
        """アルファ板が丸ごと不要だと確かめられたときに浮く分。"""
        if self.alpha and self.alpha_used is False:
            return self.pixels * (BYTES_PER_PIXEL_ALPHA - BYTES_PER_PIXEL_NO_ALPHA) * MIPMAP_FACTOR
        return 0.0

    @property
    def npot(self):
        return not (_is_pow2(self.width) and _is_pow2(self.height))


def _is_pow2(n):
    return n > 0 and (n & (n - 1)) == 0


# --- ヘッダを読む -------------------------------------------------------------

def read_png_header(head, fh):
    """PNG の IHDR と、必要なら tRNS を読む。戻り値 (w, h, alpha, note, meta)。"""
    if len(head) < 26 or head[12:16] != b"IHDR":
        raise ValueError("no IHDR at the start")
    width, height = struct.unpack(">II", head[16:24])
    bit_depth = head[24]
    color_type = head[25]
    interlace = head[28] if len(head) > 28 else 0
    meta = {"bit_depth": bit_depth, "color_type": color_type, "interlace": interlace}
    if color_type in (4, 6):
        return width, height, True, "", meta
    if color_type == 3:
        trns = _find_png_chunk(fh, b"tRNS")
        if trns is None:
            return width, height, False, "", meta
        meta["trns"] = trns
        # パレットの tRNS が全部 255 なら、そのアルファは 1 画素も透けない
        return width, height, True, "palette", meta
    return width, height, False, "", meta


def _find_png_chunk(fh, want):
    """PNG のチャンクを 1 つ探す(IDAT に着いたら諦める)。"""
    fh.seek(8)
    while True:
        head = fh.read(8)
        if len(head) < 8:
            return None
        length = struct.unpack(">I", head[0:4])[0]
        name = head[4:8]
        if name == want:
            return fh.read(length)
        if name in (b"IDAT", b"IEND"):
            return None
        fh.seek(length + 4, os.SEEK_CUR)


def read_jpeg_header(fh):
    fh.seek(2)
    while True:
        b = fh.read(1)
        if not b:
            raise ValueError("no SOF marker")
        if b != b"\xff":
            continue
        marker = fh.read(1)
        while marker == b"\xff":
            marker = fh.read(1)
        if not marker:
            raise ValueError("no SOF marker")
        m = marker[0]
        if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
            continue
        seg = fh.read(2)
        if len(seg) < 2:
            raise ValueError("truncated segment")
        length = struct.unpack(">H", seg)[0]
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            body = fh.read(5)
            if len(body) < 5:
                raise ValueError("truncated SOF")
            height, width = struct.unpack(">HH", body[1:5])
            return width, height, False, ""
        fh.seek(length - 2, os.SEEK_CUR)


def read_tga_header(head):
    if len(head) < 18:
        raise ValueError("TGA header too short")
    image_type = head[2]
    width, height = struct.unpack("<HH", head[12:16])
    depth = head[16]
    alpha_bits = head[17] & 0x0F
    if image_type not in (1, 2, 3, 9, 10, 11):
        raise ValueError("TGA image type %d" % image_type)
    if width == 0 or height == 0:
        raise ValueError("TGA size is 0")
    alpha = depth == 32 and alpha_bits > 0
    return width, height, alpha, ""


def read_bmp_header(head):
    if len(head) < 30:
        raise ValueError("BMP header too short")
    dib = struct.unpack("<I", head[14:18])[0]
    if dib < 40:
        # BITMAPCOREHEADER は寸法の位置も型も違う。読めないものは読めないと言う
        raise ValueError("BMP DIB header is %d bytes; under 40 is not read" % dib)
    width, height = struct.unpack("<ii", head[18:26])
    bpp = struct.unpack("<H", head[28:30])[0]
    return abs(width), abs(height), bpp == 32, ""


def read_gif_header(head):
    if len(head) < 10:
        raise ValueError("GIF header too short")
    width, height = struct.unpack("<HH", head[6:10])
    return width, height, None, "transparent index not inspected"


def read_psd_header(head):
    if len(head) < 26:
        raise ValueError("PSD header too short")
    channels = struct.unpack(">H", head[12:14])[0]
    height, width = struct.unpack(">II", head[14:22])
    color_mode = struct.unpack(">H", head[24:26])[0]
    # 0=Bitmap 1=Grayscale 2=Indexed 3=RGB 4=CMYK 7=Multichannel 8=Duotone 9=Lab
    base = {0: 1, 1: 1, 2: 1, 3: 3, 4: 4, 8: 1, 9: 3}.get(color_mode)
    if base is None:
        return width, height, None, "colour mode %d not read" % color_mode
    return width, height, channels > base, ""


def read_header(path, rel):
    """1 ファイルを開いてヘッダだけ読む。読めなければ ValueError。"""
    with open(path, "rb") as fh:
        head = fh.read(64)
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            w, h, a, note, meta = read_png_header(head, fh)
            t = Texture(path, rel, "png", w, h, a, note)
            t.png_meta = meta   # 後段のアルファ走査が使う
            return t
        if head.startswith(b"\xff\xd8"):
            w, h, a, note = read_jpeg_header(fh)
            return Texture(path, rel, "jpg", w, h, a, note)
        if head.startswith(b"BM"):
            w, h, a, note = read_bmp_header(head)
            return Texture(path, rel, "bmp", w, h, a, note)
        if head.startswith(b"8BPS"):
            w, h, a, note = read_psd_header(head)
            return Texture(path, rel, "psd", w, h, a, note)
        if head[:6] in (b"GIF87a", b"GIF89a"):
            w, h, a, note = read_gif_header(head)
            return Texture(path, rel, "gif", w, h, a, note)
        if path.lower().endswith(".tga"):
            w, h, a, note = read_tga_header(head)
            return Texture(path, rel, "tga", w, h, a, note)
    raise ValueError("unrecognised format")


# --- PNG のアルファだけを展開する ---------------------------------------------
#
# PNG のフィルタは「バイト単位」で、左の参照先は bpp バイト前 = 同じ画素成分の
# 1 つ前である。つまり RGBA8 のアルファ板(4 バイトおき)は、他の 3 成分と無関係に
# 単独で復元できる。展開した生バイトの 3/4 を捨てられるので、Python の逐次処理を
# 4 分の 1 に減らせる。これが「Unity 無しでも実用の速さで回る」根拠。

def _unfilter_plane(ft, cur, prev):
    if ft == 0:
        return cur
    if ft == 2:
        return bytes((c + p) & 255 for c, p in zip(cur, prev))
    out = bytearray(len(cur))
    if ft == 1:
        a = 0
        for i, c in enumerate(cur):
            a = (c + a) & 255
            out[i] = a
    elif ft == 3:
        a = 0
        for i, c in enumerate(cur):
            a = (c + ((a + prev[i]) >> 1)) & 255
            out[i] = a
    elif ft == 4:
        a = 0
        upleft = 0
        for i, x in enumerate(cur):
            b = prev[i]
            pa = abs(b - upleft)
            pb = abs(a - upleft)
            pc = abs(a + b - 2 * upleft)
            if pa <= pb and pa <= pc:
                pred = a
            elif pb <= pc:
                pred = b
            else:
                pred = upleft
            a = (x + pred) & 255
            out[i] = a
            upleft = b
    else:
        raise ValueError("unknown PNG filter %r" % (ft,))
    return bytes(out)


def png_alpha_is_used(path, meta, width, height):
    """アルファが 1 画素でも透けているか。True/False/None(調べられなかった)。"""
    color_type = meta["color_type"]
    bit_depth = meta["bit_depth"]

    if color_type == 3:
        trns = meta.get("trns")
        if trns is None:
            return False
        return any(v != 255 for v in trns)

    if color_type not in (4, 6):
        return False
    if meta.get("interlace"):
        return None
    if bit_depth not in (8, 16):
        return None

    channels = 2 if color_type == 4 else 4
    bpp = channels * (bit_depth // 8)
    stride = width * bpp
    # アルファは 1 画素の末尾に来る。8bit なら 1 バイト、16bit なら 2 バイト。
    offsets = [bpp - 1] if bit_depth == 8 else [bpp - 2, bpp - 1]

    planes_prev = [b"\x00" * width for _ in offsets]
    dec = zlib.decompressobj()
    buf = bytearray()
    used = False
    rows_done = 0
    with open(path, "rb") as fh:
        fh.seek(8)
        while rows_done < height:
            chunk_head = fh.read(8)
            if len(chunk_head) < 8:
                return None
            length = struct.unpack(">I", chunk_head[0:4])[0]
            name = chunk_head[4:8]
            if name == b"IEND":
                return None
            if name != b"IDAT":
                fh.seek(length + 4, os.SEEK_CUR)
                continue
            buf.extend(dec.decompress(fh.read(length)))
            fh.seek(4, os.SEEK_CUR)
            while len(buf) >= stride + 1 and rows_done < height:
                ft = buf[0]
                raw = bytes(buf[1:stride + 1])
                del buf[:stride + 1]
                rows_done += 1
                for k, off in enumerate(offsets):
                    plane = raw[off::bpp]
                    cur = _unfilter_plane(ft, plane, planes_prev[k])
                    planes_prev[k] = cur
                    if not used and min(cur) != 255:
                        used = True
                if used:
                    return True   # 透ける画素が 1 つ出た時点で用は済んでいる
    # while の条件が rows_done < height なので、ここに来たときは全行を読み終えている
    return used


# --- 走る -------------------------------------------------------------------

def collect(root, exts=IMAGE_EXTS):
    found, failed = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__"))
        for name in sorted(filenames):
            if not name.lower().endswith(exts):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                tex = read_header(path, rel)
            except (ValueError, OSError, struct.error) as exc:
                failed.append((rel, str(exc)))
                continue
            if tex.width <= 0 or tex.height <= 0:
                failed.append((rel, "size is 0"))
                continue
            tex.bytes_on_disk = os.path.getsize(path)
            found.append(tex)
    return found, failed


def scan_alpha(textures, max_scan_pixels=0):
    """PNG のアルファを展開して、使われているかを埋める。"""
    for tex in textures:
        if tex.kind != "png" or not tex.alpha:
            continue
        meta = tex.png_meta
        if meta is None:
            continue
        if max_scan_pixels and meta["color_type"] != 3 and tex.pixels > max_scan_pixels:
            tex.note = (tex.note + " " if tex.note else "") + "too large to scan"
            continue
        try:
            tex.alpha_used = png_alpha_is_used(tex.path, meta, tex.width, tex.height)
        except (ValueError, OSError, zlib.error, struct.error):
            tex.alpha_used = None


def fill_digests(textures):
    for tex in textures:
        h = hashlib.sha256()
        with open(tex.path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        tex.digest = h.hexdigest()


def duplicates(textures):
    by_digest = {}
    for tex in textures:
        if tex.digest:
            by_digest.setdefault(tex.digest, []).append(tex)
    return [group for group in by_digest.values() if len(group) > 1]


def rank_for(total_bytes, platform):
    mb = total_bytes / (1024 * 1024)
    for name, limit in THRESHOLDS[platform]:
        if mb <= limit:
            return name, limit
    return "Very Poor", THRESHOLDS[platform][-1][1]


# --- 出す -------------------------------------------------------------------

def _mb(n):
    return n / (1024 * 1024)


def _alpha_cell(tex):
    if tex.alpha is None:
        return "?"
    if not tex.alpha:
        return "-"
    if tex.alpha_used is True:
        return "yes"
    if tex.alpha_used is False:
        return "UNUSED"
    return "yes?"


def render(textures, failed, platform, fmt, top, elapsed, root):
    total = sum(t.est_bytes for t in textures)
    wasted = sum(t.wasted_bytes for t in textures)
    rows = sorted(textures, key=lambda t: (-t.est_bytes, t.rel))
    shown = rows[:top] if top else rows

    lines = []
    if fmt == "tsv":
        lines.append("file\tformat\twidth\theight\talpha\talpha_used\test_bytes\tnote")
        for t in rows:
            lines.append("\t".join([
                t.rel, t.kind, str(t.width), str(t.height),
                {True: "1", False: "0", None: ""}[t.alpha],
                {True: "1", False: "0", None: ""}[t.alpha_used],
                str(int(t.est_bytes)), t.note,
            ]))
        return "\n".join(lines)

    head = "| file | format | size | alpha | est |"
    sep = "|---|---|---|---|---|"
    if fmt == "md":
        lines.append("# VRChat texture audit - `%s`" % root)
        lines.append("")
        lines.append(head)
        lines.append(sep)
        for t in shown:
            lines.append("| `%s` | %s | %dx%d | %s | %.2f MB |" % (
                t.rel, t.kind, t.width, t.height, _alpha_cell(t), _mb(t.est_bytes)))
        lines.append("")
    else:
        lines.append("VRChat texture audit - %s" % root)
        lines.append("assumption: BC1/BC3 (DXT1/DXT5) + mipmaps, i.e. "
                     "0.5 B/px without alpha, 1.0 B/px with, x4/3 for mips")
        lines.append("")
        width = max([len(t.rel) for t in shown] + [4])
        width = min(width, 60)
        lines.append("%-*s  %-4s %11s  %-7s %9s" % (width, "file", "fmt", "size", "alpha", "est"))
        for t in shown:
            rel = t.rel if len(t.rel) <= width else "..." + t.rel[-(width - 3):]
            lines.append("%-*s  %-4s %11s  %-7s %8.2fM%s" % (
                width, rel, t.kind, "%dx%d" % (t.width, t.height),
                _alpha_cell(t), _mb(t.est_bytes), " *" if t.npot else ""))
        if top and len(rows) > top:
            lines.append("... and %d more (use --top 0 for all)" % (len(rows) - top))
        lines.append("")

    lines.append("%d textures, %.2f MB estimated (%.1fs)" % (len(textures), _mb(total), elapsed))
    plats = ["pc", "quest"] if platform == "both" else [platform]
    for p in plats:
        name, limit = rank_for(total, p)
        lines.append("  %-5s -> %s (%s band is <= %d MB; VRChat's own thresholds, read %s)"
                     % (p.upper(), name, name, limit, VRC_DOC_READ_ON))

    lines.append("")
    lines.append("findings:")
    any_finding = False
    unused = [t for t in textures if t.alpha and t.alpha_used is False]
    if unused:
        any_finding = True
        lines.append("  [alpha not used] %d texture(s) carry an alpha channel in which every "
                     "pixel is opaque." % len(unused))
        lines.append("                   dropping the alpha frees an estimated %.2f MB:" % _mb(wasted))
        for t in sorted(unused, key=lambda t: -t.wasted_bytes)[:10]:
            lines.append("                     %s (%dx%d, -%.2f MB)"
                         % (t.rel, t.width, t.height, _mb(t.wasted_bytes)))
    dups = duplicates(textures)
    if dups:
        any_finding = True
        dup_waste = sum(sum(t.est_bytes for t in g[1:]) for g in dups)
        lines.append("  [duplicate] %d group(s) of byte-identical files, est %.2f MB shipped twice:"
                     % (len(dups), _mb(dup_waste)))
        for g in dups[:5]:
            lines.append("                %s" % " == ".join(t.rel for t in g))
    npot = [t for t in textures if t.npot]
    if npot:
        any_finding = True
        lines.append("  [not power of two] %d texture(s), marked * above" % len(npot))
    if failed:
        any_finding = True
        lines.append("  [unread] %d file(s) could not be parsed:" % len(failed))
        for rel, why in failed[:5]:
            lines.append("             %s - %s" % (rel, why))
    unchecked = [t for t in textures if t.alpha and t.alpha_used is None]
    if unchecked:
        any_finding = True
        lines.append("  [alpha unchecked] %d texture(s); this tool only decodes PNG pixels"
                     % len(unchecked))
    if not any_finding:
        lines.append("  none")
    lines.append("")
    lines.append("the MB above is this tool's arithmetic from the stated assumption, not the number "
                 "VRChat shows. see README.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit VRChat avatar textures without opening Unity.")
    ap.add_argument("root", help="folder to walk")
    ap.add_argument("--platform", choices=("pc", "quest", "both"), default="both")
    ap.add_argument("--format", dest="fmt", choices=("text", "tsv", "md"), default="text")
    ap.add_argument("--top", type=int, default=25, help="rows to print (0 = all)")
    ap.add_argument("--no-alpha-scan", action="store_true",
                    help="do not decode PNG pixels (header only, much faster)")
    ap.add_argument("--max-scan-pixels", type=int, default=0,
                    help="skip the alpha scan above this pixel count (0 = no limit)")
    ap.add_argument("--max-mb", type=float, default=None,
                    help="exit 1 if the estimated total exceeds this")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        sys.stderr.write("not a directory: %s\n" % args.root)
        return 2

    started = time.time()
    textures, failed = collect(args.root)
    if not textures:
        sys.stderr.write(
            "read no textures under %s - a mistyped path must not print a clean report\n" % args.root)
        return 2
    if not args.no_alpha_scan:
        scan_alpha(textures, args.max_scan_pixels)
    fill_digests(textures)
    elapsed = time.time() - started

    out = render(textures, failed, args.platform, args.fmt, args.top, elapsed, args.root)
    sys.stdout.write(out + "\n")

    if args.max_mb is not None:
        total_mb = _mb(sum(t.est_bytes for t in textures))
        if total_mb > args.max_mb:
            sys.stderr.write("estimated %.2f MB exceeds --max-mb %.2f\n" % (total_mb, args.max_mb))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
