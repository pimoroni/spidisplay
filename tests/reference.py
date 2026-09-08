"""
Reference RGBA8888 or RGBA4444 -> RGB444 / RGB565 conversion, the byte-exact
semantics the C scanline kernel must reproduce.

It favours clarity over speed: it gathers the source into the full destination
pixel grid, then packs it. The kernel scatters per scanline for speed and must
still emit identical bytes, which test_scanline_c.py compares.

A rotation or mirror flips the whole destination frame along an axis, so an
off-centre image lands on the opposite side. The clockwise sense is confirmed on
a panel, a comparison against this module being unable to tell one sense from
the other.
"""


def composite_over(src, bg, alpha):
    """One channel of a premultiplied source over the background, as the C kernel.

    picovector stores colour already multiplied by its alpha, so the source is
    added rather than scaled, and this matches its blend_over_premul() byte for
    byte: the same +128 rounding bias, and the same endpoint shortcuts, which are
    what make alpha 255 pass the source through and alpha 0 give exactly the
    background. The clamp guards a hand-built entry brighter than its alpha.
    """
    if alpha == 0:
        return bg
    if alpha == 255:
        return src
    return min(src + ((bg * (255 - alpha) + 128) >> 8), 255)


def _composite_palette(palette, bg_px):
    """The 256-entry colour table an indexed source is drawn through, composited.

    Mirrors prepare_palette() in scanline.hpp: the table is clamped to 256 RGBA
    words and its tail zeroed, so an index past the supplied entries reads as
    transparent and resolves to the background.
    """
    pal = bytes(palette[:1024])
    pal += bytes(1024 - len(pal))
    return [tuple(composite_over(pal[i + c], bg_px[c], pal[i + 3]) for c in range(3))
            for i in range(0, 1024, 4)]


# tile's third state: each repeat alternates between normal and reversed, so
# every seam is a reflection. False and True remain the other two.
MIRROR = 2

# The direct source formats, named by their bit layout as fmt names the packers.
# RGBA4444 is picovector's little-endian 16-bit word: R in bits 0-3, G in 4-7, B in
# 8-11 and A in 12-15, so byte 0 is G:R and byte 1 is A:B.
_SRC_BYTES = {8888: 4, 4444: 2}


def expand_rgba4444(src):
    """RGBA4444 bytes as the RGBA8888 bytes the kernel's loader sees them as.

    Each nibble is scaled by 17, taking 0 to 0 and 15 to 255, the expansion
    picovector's pv_expand4444 applies before any blend.
    """
    out = bytearray()
    for i in range(0, len(src), 2):
        lo, hi = src[i], src[i + 1]
        out += bytes(((lo & 0x0f) * 17, (lo >> 4) * 17, (hi & 0x0f) * 17, (hi >> 4) * 17))
    return bytes(out)


def sample_grid(src, src_w, src_h, dst_w, dst_h, rotation=0, mirror=False,
                double=False, offset=None, tile=False, bg=0, stride=None,
                palette=None, src_format=8888):
    """Gather the source into a dst_h x dst_w grid of (r, g, b) tuples.

    Placement model: the source is composed at its offset in an upright canvas
    (the image's own orientation), then the whole screen is rigidly rotated
    clockwise by rotation, and finally mirror horizontally-flips the output. So
    the origin corner and the offset rotate/flip with the image, as if a person
    physically rotated or flipped the panel.

    src is direct pixels in src_format, RGBA8888 (4 bytes per pixel) or RGBA4444
    (2 bytes), or one palette index per pixel when palette holds RGBA8888 words,
    colour premultiplied by alpha as picovector stores it. bg is a 0xBBGGRR
    integer, which the pixels the source does not cover take, and which a
    palette entry's alpha composites over; a direct pixel's alpha is ignored.
    offset is None (centre both axes)
    or (x, y) in the upright canvas, where either element may be None to centre
    just that axis. stride is the source pitch in bytes, None meaning contiguous.
    tile is one value for both source axes or an (x, y) pair of them: a tiled
    axis repeats the source instead of running out of it, so any offset is
    valid, and MIRROR reverses every other repeat so each seam is a reflection.
    Returns the grid before packing.
    """
    if rotation not in (0, 90, 180, 270):
        raise ValueError(f"invalid rotation {rotation}")

    if not isinstance(tile, (tuple, list)):
        tile = (tile, tile)
    tile_x, tile_y = tile

    src_bytes = _SRC_BYTES[src_format] if palette is None else 1
    if stride is None:
        stride = src_w * src_bytes
    scale = 2 if double else 1
    region_w, region_h = src_w * scale, src_h * scale  # source extent, unrotated

    # Upright canvas dimensions (rotating it gives the dst_w x dst_h output).
    canvas_w, canvas_h = (dst_h, dst_w) if rotation in (90, 270) else (dst_w, dst_h)

    ox = oy = None
    if offset is not None:
        ox, oy = offset
    off_x = ((canvas_w - region_w) >> 1) if ox is None else ox
    off_y = ((canvas_h - region_h) >> 1) if oy is None else oy

    bg_px = (bg & 0xff, (bg >> 8) & 0xff, (bg >> 16) & 0xff)
    table = None if palette is None else _composite_palette(palette, bg_px)
    grid = [[bg_px] * dst_w for _ in range(dst_h)]

    for dst_y in range(dst_h):
        for dst_x in range(dst_w):
            # Un-mirror (mirror flips the final output), then inverse-rotate the
            # output pixel back to the upright canvas coordinate.
            mx = (dst_w - 1 - dst_x) if mirror else dst_x
            my = dst_y
            if rotation == 0:
                cx, cy = mx, my
            elif rotation == 90:
                cx, cy = my, dst_w - 1 - mx
            elif rotation == 180:
                cx, cy = dst_w - 1 - mx, dst_h - 1 - my
            else:  # 270
                cx, cy = dst_h - 1 - my, mx

            u = cx - off_x
            v = cy - off_y
            if tile_x == MIRROR:
                u %= 2 * region_w
                if u >= region_w:
                    u = 2 * region_w - 1 - u
            elif tile_x:
                u %= region_w
            if tile_y == MIRROR:
                v %= 2 * region_h
                if v >= region_h:
                    v = 2 * region_h - 1 - v
            elif tile_y:
                v %= region_h
            if 0 <= u < region_w and 0 <= v < region_h:
                si = (v // scale) * stride + (u // scale) * src_bytes
                if table is not None:
                    grid[dst_y][dst_x] = table[src[si]]
                elif src_bytes == 2:
                    lo, hi = src[si], src[si + 1]
                    grid[dst_y][dst_x] = ((lo & 0x0f) * 17, (lo >> 4) * 17,
                                          (hi & 0x0f) * 17)
                else:
                    # A direct source's alpha is ignored, see pixel_formats.hpp
                    grid[dst_y][dst_x] = (src[si], src[si + 1], src[si + 2])

    return grid


def pack(grid, dst_w, dst_h, fmt):
    """Pack a pixel grid into panel bytes. fmt is 444 or 565."""
    if fmt == 444:
        return _pack_rgb444(grid, dst_w, dst_h)
    if fmt == 565:
        return _pack_rgb565(grid, dst_w, dst_h)
    raise ValueError(f"unsupported format {fmt}")


def _pack_rgb444(grid, dst_w, dst_h):
    if dst_w & 1:
        raise ValueError("RGB444 requires an even destination width")
    out = bytearray((dst_w * dst_h * 3) // 2)
    di = 0
    for dst_y in range(dst_h):
        row = grid[dst_y]
        for dst_x in range(0, dst_w, 2):
            r0, g0, b0 = row[dst_x]
            r1, g1, b1 = row[dst_x + 1]
            out[di] = (r0 & 0xf0) | (g0 >> 4)          # R1 | G1
            out[di + 1] = (b0 & 0xf0) | (r1 >> 4)      # B1 | R2
            out[di + 2] = (g1 & 0xf0) | (b1 >> 4)      # G2 | B2
            di += 3
    return bytes(out)


def _pack_rgb565(grid, dst_w, dst_h):
    out = bytearray(dst_w * dst_h * 2)
    di = 0
    for dst_y in range(dst_h):
        for r, g, b in grid[dst_y]:
            value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out[di] = (value >> 8) & 0xff
            out[di + 1] = value & 0xff
            di += 2
    return bytes(out)


def convert(src, src_w, src_h, dst_w, dst_h, rotation=0, mirror=False,
            double=False, offset=None, tile=False, bg=0, fmt=444, stride=None,
            palette=None, src_format=8888):
    """Convert direct or palette-indexed source bytes into packed panel bytes."""
    grid = sample_grid(src, src_w, src_h, dst_w, dst_h, rotation, mirror,
                       double, offset, tile, bg, stride, palette, src_format)
    return pack(grid, dst_w, dst_h, fmt)


def unpack(data, dst_w, dst_h, fmt):
    """Decode packed bytes back to a grid of reduced-precision (r, g, b).

    For tests: values keep only the bits the format preserves (the RGB444 top
    nibble, or RGB565's 5/6/5), low bits zeroed.
    """
    if fmt == 444:
        return _unpack_rgb444(data, dst_w, dst_h)
    if fmt == 565:
        return _unpack_rgb565(data, dst_w, dst_h)
    raise ValueError(f"unsupported format {fmt}")


def _unpack_rgb444(data, dst_w, dst_h):
    grid = []
    di = 0
    for _ in range(dst_h):
        row = []
        for _ in range(0, dst_w, 2):
            b0, b1, b2 = data[di], data[di + 1], data[di + 2]
            row.append((b0 & 0xf0, (b0 & 0x0f) << 4, b1 & 0xf0))
            row.append(((b1 & 0x0f) << 4, b2 & 0xf0, (b2 & 0x0f) << 4))
            di += 3
        grid.append(row)
    return grid


def _unpack_rgb565(data, dst_w, dst_h):
    grid = []
    di = 0
    for _ in range(dst_h):
        row = []
        for _ in range(dst_w):
            value = (data[di] << 8) | data[di + 1]
            row.append((((value >> 11) & 0x1f) << 3,
                        ((value >> 5) & 0x3f) << 2,
                        (value & 0x1f) << 3))
            di += 2
        grid.append(row)
    return grid
