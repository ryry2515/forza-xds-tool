"""Decode the base mip level of a .xds texture (raw Xbox 360 texture) to PNG.

Usage: python xds_tool.py in.xds [out.png]
       python xds_tool.py encode new.png original.xds out.xds   (8888 and DXT5 textures)
Needs numpy. Supported formats: 0x35 (DXT5, also encoded), 0x12 (DXT1), 0x13 (DXT3),
0x06 and 0x32 (8888). Other formats are reported and skipped.

Steps: parse the 52-byte header (see xds_info.py), undo the endian swap
(header field "endianness", d1 bits 6-7), un-tile (Xbox 360 2D tiling, in
units of pixels or 4x4 blocks), then decode the pixels.
"""
import struct
import sys
import zlib

import numpy as np

FORMATS = {
    0x06: ("8888", 4, 2),
    0x32: ("8888", 4, 2),
    0x12: ("DXT1", 8, 3),
    0x13: ("DXT3", 16, 4),
    0x35: ("DXT5", 16, 4),
}


def parse_header(data):
    w = struct.unpack(">13I", data[:52])
    d0, d1, d2 = w[7], w[8], w[9]
    return {
        "tiled": bool(d0 >> 31),
        "pitch_px": ((d0 >> 22) & 0x1FF) * 32,
        "format": d1 & 0x3F,
        "endian": (d1 >> 6) & 3,
        "width": (d2 & 0x1FFF) + 1,
        "height": ((d2 >> 13) & 0x1FFF) + 1,
    }


def swap(buf, mode):
    a = np.frombuffer(buf, dtype=np.uint8)
    if mode == 1:      # 8 in 16
        n = len(a) // 2 * 2
        a = a[:n].reshape(-1, 2)[:, ::-1]
    elif mode == 2:    # 8 in 32
        n = len(a) // 4 * 4
        a = a[:n].reshape(-1, 4)[:, ::-1]
    elif mode == 3:    # 16 in 32
        n = len(a) // 4 * 4
        a = a[:n].reshape(-1, 2, 2)[:, ::-1, :]
    return np.ascontiguousarray(a).reshape(-1)


def tiled_offsets(w_units, h_units, log_bpp):
    """Byte offset of every (x, y) unit in the Xbox 360 2D tiled layout."""
    aw = (w_units + 31) & ~31
    y = np.arange(h_units, dtype=np.int64)[:, None]
    x = np.arange(w_units, dtype=np.int64)[None, :]
    macro = ((y >> 5) * (aw >> 5)) << (log_bpp + 7)
    micro = ((y & 6) << 2) << log_bpp
    base = (macro + ((micro & ~0xF) << 1) + (micro & 0xF)
            + ((y & 8) << (3 + log_bpp)) + ((y & 1) << 4))
    macro2 = (x >> 5) << (log_bpp + 7)
    micro2 = (x & 7) << log_bpp
    off = base + (macro2 + ((micro2 & ~0xF) << 1) + (micro2 & 0xF))
    return (((off & ~0x1FF) << 3) + ((y & 16) << 7) + ((off & 0x1C0) << 2)
            + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) + (off & 0x3F))


def untile(buf, w_units, h_units, bytes_per_unit, log_bpp, tiled=True):
    if not tiled:
        return np.frombuffer(buf, np.uint8)[: w_units * h_units * bytes_per_unit].reshape(h_units, w_units, bytes_per_unit)
    off = tiled_offsets(w_units, h_units, log_bpp)
    a = np.frombuffer(buf, np.uint8)
    idx = off[..., None] + np.arange(bytes_per_unit)[None, None, :]
    return a[idx]


def rgb565(v):
    r = ((v >> 11) & 31) * 255 // 31
    g = ((v >> 5) & 63) * 255 // 63
    b = (v & 31) * 255 // 31
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def decode_color(c0, c1, bits, dxt1_alpha=False):
    p0, p1 = rgb565(c0).astype(np.int32), rgb565(c1).astype(np.int32)
    pal = np.zeros(c0.shape + (4, 3), np.int32)
    pal[..., 0, :], pal[..., 1, :] = p0, p1
    four = (c0 > c1) | (not dxt1_alpha)
    pal[..., 2, :] = np.where(four[..., None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[..., 3, :] = np.where(four[..., None], (p0 + 2 * p1) // 3, 0)
    sel = (bits[..., None] >> (2 * np.arange(16))) & 3
    return np.take_along_axis(pal, sel[..., None].repeat(3, -1), axis=-2)  # (...,16,3)


def decode_blocks(blocks, kind):
    """blocks: (H, W, bytes) little-endian DXT blocks -> (H*4, W*4, 4) RGBA."""
    h, w, _ = blocks.shape
    b = blocks.astype(np.uint32)
    if kind == "DXT1":
        cb = b[..., 0:8]
    else:
        cb = b[..., 8:16]
    c0 = cb[..., 0] | (cb[..., 1] << 8)
    c1 = cb[..., 2] | (cb[..., 3] << 8)
    bits = cb[..., 4] | (cb[..., 5] << 8) | (cb[..., 6] << 16) | (cb[..., 7] << 24)
    rgb = decode_color(c0, c1, bits, dxt1_alpha=(kind == "DXT1"))
    alpha = np.full((h, w, 16), 255, np.int32)
    if kind == "DXT3":
        a = b[..., 0:8]
        for i in range(16):
            nib = (a[..., i // 2] >> (4 * (i % 2))) & 15
            alpha[..., i] = nib * 17
    elif kind == "DXT5":
        a0, a1 = b[..., 0].astype(np.int32), b[..., 1].astype(np.int32)
        abits = np.zeros((h, w), np.uint64)
        for i in range(6):
            abits |= b[..., 2 + i].astype(np.uint64) << np.uint64(8 * i)
        tab = np.zeros((h, w, 8), np.int32)
        tab[..., 0], tab[..., 1] = a0, a1
        big = (a0 > a1)[..., None]
        for k in range(1, 7):
            tab[..., k + 1] = np.where(big[..., 0], ((7 - k) * a0 + k * a1) // 7, 0)
        for k in range(1, 5):
            tab[..., k + 1] = np.where(big[..., 0], tab[..., k + 1], ((5 - k) * a0 + k * a1) // 5)
        tab[..., 6] = np.where(big[..., 0], tab[..., 6], 0)
        tab[..., 7] = np.where(big[..., 0], tab[..., 7], 255)
        for i in range(16):
            sel = ((abits >> np.uint64(3 * i)) & np.uint64(7)).astype(np.int64)
            alpha[..., i] = np.take_along_axis(tab, sel[..., None], -1)[..., 0]
    elif kind == "DXT1":
        c = c0 <= c1
        for i in range(16):
            sel = (bits >> (2 * i)) & 3
            alpha[..., i] = np.where(c & (sel == 3), 0, 255)
    px = np.concatenate([rgb, alpha[..., None]], axis=-1).astype(np.uint8)  # (h,w,16,4)
    px = px.reshape(h, w, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(h * 4, w * 4, 4)
    return px


def decode(data):
    hd = parse_header(data)
    fmt = FORMATS.get(hd["format"])
    if not fmt:
        raise ValueError("unsupported format 0x%02x" % hd["format"])
    kind, bpu, log = fmt
    body = swap(data[52:], hd["endian"])
    W, H = hd["width"], hd["height"]
    if kind == "8888":
        u = untile(body, W, H, 4, 2, hd["tiled"])
        bgra = u
        rgba = np.stack([bgra[..., 2], bgra[..., 1], bgra[..., 0], bgra[..., 3]], -1)  # bytes are B,G,R,A after the swap
        return rgba[:H, :W], hd
    bw, bh = (W + 3) // 4, (H + 3) // 4
    blocks = untile(body, bw, bh, bpu, log, hd["tiled"])
    return decode_blocks(blocks, kind)[:H, :W], hd


def write_png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)


def encode_8888(rgba, template):
    """RGBA array (H, W, 4) -> .xds bytes for an 8888 texture (format 0x06 or 0x32).

    `template` is the original .xds bytes: its 52-byte header is reused, so the
    new image must have the same width and height. Base level only (no mips)."""
    hd = parse_header(template)
    if FORMATS.get(hd["format"], ("",))[0] != "8888":
        raise ValueError("template is not an 8888 texture")
    H, W = hd["height"], hd["width"]
    if rgba.shape[:2] != (H, W):
        raise ValueError("image must be %d x %d" % (W, H))
    rgba = np.asarray(rgba, np.uint8)
    bgra = np.stack([rgba[..., 2], rgba[..., 1], rgba[..., 0], rgba[..., 3]], -1)
    size = len(template) - 52
    out = np.zeros(size, np.uint8)
    off = tiled_offsets(W, H, 2) if hd["tiled"] else (np.arange(H)[:, None] * W + np.arange(W)[None, :]) * 4
    idx = off[..., None] + np.arange(4)[None, None, :]
    out[idx] = bgra
    out = swap(out.tobytes(), hd["endian"])  # the swaps are their own inverse
    return template[:52] + out.tobytes()


# ---- DXT5 encoding ---------------------------------------------------------
def mip_layout(W, H, block_bytes=16):
    """Levels stored as whole 32x32-block tiles; levels with a side <= 16 px share one tail tile.
    Returns (levels, tail_offset); levels = [(offset, w, h, blocks_w_aligned, blocks_h_aligned)]."""
    levels, off, n = [], 0, 0
    while True:
        w, h = max(1, W >> n), max(1, H >> n)
        if min(w, h) <= 16:
            break
        bw = ((w + 3) // 4 + 31) & ~31
        bh = ((h + 3) // 4 + 31) & ~31
        levels.append((off, w, h, bw, bh))
        off += bw * bh * block_bytes
        n += 1
    return levels, off


def _quantize565(c):
    r = np.clip(np.rint(c[..., 0] * 31 / 255), 0, 31).astype(np.int32)
    g = np.clip(np.rint(c[..., 1] * 63 / 255), 0, 63).astype(np.int32)
    b = np.clip(np.rint(c[..., 2] * 31 / 255), 0, 31).astype(np.int32)
    return (r << 11) | (g << 5) | b


def compress_dxt5(rgba):
    """RGBA (H, W, 4) uint8 -> blocks (H/4, W/4, 16) uint8, little-endian DXT5. Simple min/max range fit."""
    h, w, _ = rgba.shape
    ph, pw = (h + 3) // 4 * 4, (w + 3) // 4 * 4
    if (ph, pw) != (h, w):
        rgba = np.pad(rgba, ((0, ph - h), (0, pw - w), (0, 0)), mode="edge")
    bh, bw = ph // 4, pw // 4
    px = rgba.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh, bw, 16, 4).astype(np.float32)
    rgb, a = px[..., :3], px[..., 3]
    lo, hi = rgb.min(axis=2), rgb.max(axis=2)
    inset = (hi - lo) / 16.0
    q0 = _quantize565(hi - inset)   # c0 (larger)
    q1 = _quantize565(lo + inset)   # c1
    c0, c1 = np.maximum(q0, q1), np.minimum(q0, q1)
    p0, p1 = rgb565(c0).astype(np.float32), rgb565(c1).astype(np.float32)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=2)         # (bh,bw,4,3)
    dist = ((rgb[:, :, :, None, :] - pal[:, :, None, :, :]) ** 2).sum(-1)           # (bh,bw,16,4)
    idx = dist.argmin(axis=-1).astype(np.uint32)
    cbits = np.zeros((bh, bw), np.uint32)
    for i in range(16):
        cbits |= idx[..., i] << np.uint32(2 * i)
    a0, a1 = a.max(axis=2), a.min(axis=2)       # a0 >= a1: 8-value mode when a0 > a1
    tab = np.stack([a0 + (a1 - a0) * k / 7.0 for k in range(8)], axis=2)           # a0 .. a1 in 7 steps
    ad = np.abs(a[:, :, :, None] - tab[:, :, None, :])
    aidx = ad.argmin(axis=-1).astype(np.uint64)
    abits = np.zeros((bh, bw), np.uint64)
    for i in range(16):
        abits |= aidx[..., i] << np.uint64(3 * i)
    out = np.zeros((bh, bw, 16), np.uint8)
    out[..., 0], out[..., 1] = a0.astype(np.uint8), a1.astype(np.uint8)
    for i in range(6):
        out[..., 2 + i] = ((abits >> np.uint64(8 * i)) & np.uint64(255)).astype(np.uint8)
    out[..., 8], out[..., 9] = (c0 & 255).astype(np.uint8), (c0 >> 8).astype(np.uint8)
    out[..., 10], out[..., 11] = (c1 & 255).astype(np.uint8), (c1 >> 8).astype(np.uint8)
    for i in range(4):
        out[..., 12 + i] = ((cbits >> np.uint32(8 * i)) & 255).astype(np.uint8)
    return out


def _tile_level(blocks, bw_al, bh_al):
    bh, bw, nbytes = blocks.shape
    buf = np.zeros(bw_al * bh_al * nbytes, np.uint8)
    off = tiled_offsets(bw, bh, 4)
    buf[off[..., None] + np.arange(nbytes)[None, None, :]] = blocks
    return buf


def encode_dxt5(rgba, template, mips=True):
    """RGBA (H, W, 4) -> .xds bytes for a DXT5 (0x35) texture, reusing the template's header.
    Base level and every mip down to 32 px are recompressed (box-filtered); the small tail tile
    (levels of 16 px and below) is copied unchanged from the template."""
    hd = parse_header(template)
    if hd["format"] != 0x35:
        raise ValueError("template is not a DXT5 (0x35) texture")
    W, H = hd["width"], hd["height"]
    if rgba.shape[:2] != (H, W):
        raise ValueError("image must be %d x %d" % (W, H))
    levels, tail = mip_layout(W, H)
    body = swap(template[52:], hd["endian"]).copy()   # start from the original, replace levels
    cur = np.asarray(rgba, np.uint8)
    for i, (off, w, h, bw_al, bh_al) in enumerate(levels):
        if i > 0 and not mips:
            break
        if i > 0:
            f = cur.astype(np.float32)
            f = f[: (f.shape[0] // 2) * 2, : (f.shape[1] // 2) * 2]
            f = (f[0::2, 0::2] + f[1::2, 0::2] + f[0::2, 1::2] + f[1::2, 1::2]) / 4.0
            cur = np.rint(f).astype(np.uint8)
        blocks = compress_dxt5(cur)
        body[off: off + bw_al * bh_al * 16] = _tile_level(blocks, bw_al, bh_al)
    out = swap(body.tobytes(), hd["endian"])
    return template[:52] + out.tobytes()


def read_png(path):
    from PIL import Image  # only needed for PNG input
    return np.asarray(Image.open(path).convert("RGBA"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "encode":
        # python xds_tool.py encode new.png original.xds out.xds  (8888 and DXT5 textures)
        tpl = open(sys.argv[3], "rb").read()
        enc = encode_dxt5 if parse_header(tpl)["format"] == 0x35 else encode_8888
        data = enc(read_png(sys.argv[2]), tpl)
        open(sys.argv[4], "wb").write(data)
        print("wrote", sys.argv[4], len(data), "bytes")
        sys.exit(0)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + ".png"
    img, hd = decode(open(src, "rb").read())
    write_png(dst, img)
    print(src, "->", dst, img.shape, "format 0x%02x" % hd["format"])
