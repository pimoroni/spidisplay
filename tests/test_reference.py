"""
Tests for the reference RGBA8888 -> RGB444 / RGB565 conversion.

These pin the byte-exact placement, transform, and packing semantics that the C
scanline kernel must reproduce in phase 2. Runnable under pytest (the tox/CI
path) or directly as a script for local iteration without pytest installed.

Orientation for the rotate cases is derived from st7789.py and locked here up to
the clockwise/counter-clockwise sense, which an on-device capture confirms
(plan phases 3 and 4). The properties below (180 is a double flip, four 90s are
the identity) fix everything else.
"""

import reference

ROTATIONS = (0, 90, 180, 270)


def _encode_src(src_w, src_h):
    """RGBA source whose top nibbles encode coordinates: R nibble = x, G = y.

    Requires src_w, src_h <= 15 so each coordinate fits a nibble. The 0x08 low
    bits keep values mid-range so nibble rounding is unambiguous.
    """
    assert src_w <= 15 and src_h <= 15
    out = bytearray(src_w * src_h * 4)
    i = 0
    for y in range(src_h):
        for x in range(src_w):
            out[i] = (x << 4) | 0x08
            out[i + 1] = (y << 4) | 0x08
            out[i + 2] = 0x08
            out[i + 3] = 0xff
            i += 4
    return bytes(out)


def _coord_of(pixel):
    """Recover (x, y) encoded by _encode_src from an unpacked (r, g, b)."""
    return (pixel[0] >> 4, pixel[1] >> 4)


def _grid_to_src(grid):
    """Turn a full (r, g, b) grid back into RGBA source bytes (opaque)."""
    out = bytearray(len(grid) * len(grid[0]) * 4)
    i = 0
    for row in grid:
        for r, g, b in row:
            out[i], out[i + 1], out[i + 2], out[i + 3] = r, g, b, 0xff
            i += 4
    return bytes(out)


def _bbox(grid, bg_px):
    """Bounding box (x0, y0, x1, y1) of non-background pixels, inclusive."""
    xs, ys = [], []
    for y, row in enumerate(grid):
        for x, px in enumerate(row):
            if px != bg_px:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys))


def test_pack_lengths():
    grid = reference.sample_grid(_encode_src(4, 4), 4, 4, 4, 4)
    assert len(reference.pack(grid, 4, 4, 444)) == 4 * 4 * 3 // 2
    assert len(reference.pack(grid, 4, 4, 565)) == 4 * 4 * 2


def test_odd_width_rejected_for_rgb444():
    grid = reference.sample_grid(_encode_src(3, 2), 3, 2, 3, 2)
    try:
        reference.pack(grid, 3, 2, 444)
    except ValueError:
        return
    raise AssertionError("expected ValueError for odd RGB444 width")


def test_identity_full_cover():
    src_w, src_h = 6, 4
    src = _encode_src(src_w, src_h)
    for fmt in (444, 565):
        data = reference.convert(src, src_w, src_h, src_w, src_h, fmt=fmt)
        grid = reference.unpack(data, src_w, src_h, fmt)
        for y in range(src_h):
            for x in range(src_w):
                assert _coord_of(grid[y][x]) == (x, y), (fmt, x, y)


def test_mirror_x():
    src_w, src_h = 6, 4
    data = reference.convert(_encode_src(src_w, src_h), src_w, src_h, src_w, src_h,
                             rotation=0, mirror=True)
    grid = reference.unpack(data, src_w, src_h, 444)
    for y in range(src_h):
        for x in range(src_w):
            assert _coord_of(grid[y][x]) == (src_w - 1 - x, y)


def test_180_is_double_flip():
    src_w, src_h = 6, 4
    src = _encode_src(src_w, src_h)
    grid = reference.unpack(reference.convert(src, src_w, src_h, src_w, src_h,
                                              rotation=180), src_w, src_h, 444)
    for y in range(src_h):
        for x in range(src_w):
            assert _coord_of(grid[y][x]) == (src_w - 1 - x, src_h - 1 - y)


def test_rotate_swaps_region_dims():
    # Source 4 wide, 2 tall. Rotated placement should be 2 wide, 4 tall.
    src_w, src_h = 4, 2
    bg = 0x0000F0
    bg_px = (0xF0, 0x00, 0x00)
    for rotation in (90, 270):
        grid = reference.sample_grid(_encode_src(src_w, src_h), src_w, src_h,
                                     8, 8, rotation=rotation, bg=bg)
        x0, y0, x1, y1 = _bbox(grid, bg_px)
        assert (x1 - x0 + 1, y1 - y0 + 1) == (src_h, src_w), rotation


def test_four_90s_are_identity():
    n = 4
    src = _encode_src(n, n)
    grid = reference.sample_grid(src, n, n, n, n, rotation=90)
    for _ in range(3):
        grid = reference.sample_grid(_grid_to_src(grid), n, n, n, n, rotation=90)
    ref = reference.sample_grid(src, n, n, n, n, rotation=0)
    assert grid == ref


def test_90_twice_is_180():
    n = 4
    src = _encode_src(n, n)
    once = reference.sample_grid(src, n, n, n, n, rotation=90)
    twice = reference.sample_grid(_grid_to_src(once), n, n, n, n, rotation=90)
    assert twice == reference.sample_grid(src, n, n, n, n, rotation=180)


def test_centred_placement_and_bg_fill():
    src_w, src_h = 2, 2
    bg = 0x0000F0
    bg_px = (0xF0, 0x00, 0x00)
    grid = reference.sample_grid(_encode_src(src_w, src_h), src_w, src_h,
                                 6, 4, bg=bg)
    # Centred: offset ((6-2)/2, (4-2)/2) = (2, 1).
    assert _bbox(grid, bg_px) == (2, 1, 3, 2)
    assert grid[0][0] == bg_px
    assert _coord_of(grid[1][2]) == (0, 0)
    assert _coord_of(grid[2][3]) == (1, 1)


def test_explicit_offset_with_clipping():
    # Place a 4x4 source at (-1, -1): its top-left column/row are clipped off.
    src_w, src_h = 4, 4
    bg = 0x0000F0
    grid = reference.sample_grid(_encode_src(src_w, src_h), src_w, src_h,
                                 6, 6, offset=(-1, -1), bg=bg)
    # dst (0,0) samples src (1,1); src column/row 0 never appear.
    assert _coord_of(grid[0][0]) == (1, 1)
    for row in grid:
        for px in row:
            if px != (bg & 0xff, 0, 0):
                assert _coord_of(px)[0] >= 1 and _coord_of(px)[1] >= 1


def test_pixel_double_expands_2x2():
    src_w, src_h = 3, 2
    grid = reference.sample_grid(_encode_src(src_w, src_h), src_w, src_h,
                                 6, 4, double=True, offset=(0, 0))
    # Each source pixel fills a 2x2 destination block.
    for sy in range(src_h):
        for sx in range(src_w):
            for dy in (2 * sy, 2 * sy + 1):
                for dx in (2 * sx, 2 * sx + 1):
                    assert _coord_of(grid[dy][dx]) == (sx, sy)


def test_odd_source_width_places_and_pads():
    # 5x3 is the historical shearing case; must place cleanly with bg pad.
    src_w, src_h = 5, 3
    bg = 0x0000F0
    bg_px = (0xF0, 0x00, 0x00)
    dst_w, dst_h = 8, 4
    data = reference.convert(_encode_src(src_w, src_h), src_w, src_h,
                             dst_w, dst_h, bg=bg, fmt=444)
    assert len(data) == dst_w * dst_h * 3 // 2
    grid = reference.unpack(data, dst_w, dst_h, 444)
    # Centred: offset ((8-5)/2, (4-3)/2) = (1, 0).
    x0, y0, x1, y1 = _bbox(grid, bg_px)
    assert (x0, y0, x1, y1) == (1, 0, 5, 2)
    assert _coord_of(grid[0][1]) == (0, 0)
    assert _coord_of(grid[2][5]) == (4, 2)


def test_rgb565_packs_known_pixel():
    # Single full-cover pixel, check the big-endian 5/6/5 encoding directly.
    src = bytes((0xFF, 0x80, 0x00, 0xFF)) * 2  # 2x1 red-ish
    data = reference.convert(src, 2, 1, 2, 1, fmt=565)
    value = (data[0] << 8) | data[1]
    assert value == ((0xFF >> 3) << 11) | ((0x80 >> 2) << 5) | (0x00 >> 3)


def _repeat_src(src, src_w, src_h, nx, ny):
    """The source repeated nx times across and ny times down, as RGBA bytes."""
    row_bytes = src_w * 4
    rows = [src[y * row_bytes:(y + 1) * row_bytes] * nx for y in range(src_h)]
    return b"".join(rows) * ny


def test_tile_matches_hand_tiling():
    # A tiled read over one source must equal a plain read over the source
    # repeated far enough to cover the canvas, at the offset reduced by one
    # period so the repeats start left of and above the frame.
    src_w, src_h = 4, 3
    src = _encode_src(src_w, src_h)
    bg = 0x0000F0
    dst_w, dst_h = 8, 6
    for rotation in ROTATIONS:
        for mirror in (False, True):
            for double in (False, True):
                for tile in ((True, False), (False, True), (True, True)):
                    for offset in ((0, 0), (2, 1), (-5, -7), (9, 14)):
                        scale = 2 if double else 1
                        canvas_w, canvas_h = ((dst_h, dst_w) if rotation in (90, 270)
                                              else (dst_w, dst_h))
                        region_w, region_h = src_w * scale, src_h * scale
                        tile_x, tile_y = tile
                        nx = (canvas_w // region_w) + 3 if tile_x else 1
                        ny = (canvas_h // region_h) + 3 if tile_y else 1
                        hand_x = offset[0] % region_w - region_w if tile_x else offset[0]
                        hand_y = offset[1] % region_h - region_h if tile_y else offset[1]
                        big = _repeat_src(src, src_w, src_h, nx, ny)
                        got = reference.sample_grid(
                            src, src_w, src_h, dst_w, dst_h, rotation=rotation,
                            mirror=mirror, double=double, offset=offset, bg=bg,
                            tile=tile)
                        ref = reference.sample_grid(
                            big, src_w * nx, src_h * ny, dst_w, dst_h,
                            rotation=rotation, mirror=mirror, double=double,
                            offset=(hand_x, hand_y), bg=bg)
                        assert got == ref, (rotation, mirror, double, tile, offset)


def test_tile_offset_is_periodic():
    # With tiling on, offsets one period apart are the same frame, negatives
    # included, so a caller's offset never needs reducing.
    src_w, src_h = 3, 2
    src = _encode_src(src_w, src_h)
    base = reference.sample_grid(src, src_w, src_h, 6, 4, offset=(1, 1), tile=True)
    for periods_x, periods_y in ((1, 0), (0, 1), (-3, 2), (100, -100)):
        moved = reference.sample_grid(
            src, src_w, src_h, 6, 4,
            offset=(1 + periods_x * src_w, 1 + periods_y * src_h), tile=True)
        assert moved == base, (periods_x, periods_y)


def _flip_src_x(src, src_w, src_h):
    """The source reversed along x, as RGBA bytes."""
    row_bytes = src_w * 4
    out = bytearray()
    for y in range(src_h):
        row = src[y * row_bytes:(y + 1) * row_bytes]
        out += b"".join(row[x * 4:(x + 1) * 4] for x in reversed(range(src_w)))
    return bytes(out)


def _flip_src_y(src, src_w, src_h):
    """The source reversed along y, as RGBA bytes."""
    row_bytes = src_w * 4
    return b"".join(src[y * row_bytes:(y + 1) * row_bytes]
                    for y in reversed(range(src_h)))


def _expand_x(src, src_w, src_h, count, mode):
    """count copies across, alternately reflected under MIRROR."""
    if mode == reference.MIRROR:
        flipped = _flip_src_x(src, src_w, src_h)
        row_bytes = src_w * 4
        return b"".join(
            b"".join((src if i % 2 == 0 else flipped)[y * row_bytes:(y + 1) * row_bytes]
                     for i in range(count))
            for y in range(src_h))
    return _repeat_src(src, src_w, src_h, count, 1)


def _expand_y(src, src_w, src_h, count, mode):
    """count copies down, alternately reflected under MIRROR."""
    if mode == reference.MIRROR:
        flipped = _flip_src_y(src, src_w, src_h)
        return b"".join(src if i % 2 == 0 else flipped for i in range(count))
    return src * count


def test_mirror_tile_matches_hand_tiling():
    # A mirrored read over one source must equal a plain read over the source
    # repeated with alternating reflections, at the offset reduced by one
    # doubled period so the repeats start on an unreflected copy.
    src_w, src_h = 4, 3
    src = _encode_src(src_w, src_h)
    bg = 0x0000F0
    dst_w, dst_h = 8, 6
    modes = ((reference.MIRROR, False), (False, reference.MIRROR),
             (reference.MIRROR, reference.MIRROR), (reference.MIRROR, True))
    for rotation in ROTATIONS:
        for mirror in (False, True):
            for double in (False, True):
                for tile in modes:
                    for offset in ((0, 0), (2, 1), (-5, -7), (9, 14)):
                        scale = 2 if double else 1
                        canvas_w, canvas_h = ((dst_h, dst_w) if rotation in (90, 270)
                                              else (dst_w, dst_h))
                        region_w, region_h = src_w * scale, src_h * scale
                        tile_x, tile_y = tile
                        period_x = 2 * region_w if tile_x == reference.MIRROR else region_w
                        period_y = 2 * region_h if tile_y == reference.MIRROR else region_h
                        nx = ((canvas_w + period_x) // region_w + 2) if tile_x else 1
                        ny = ((canvas_h + period_y) // region_h + 2) if tile_y else 1
                        hand_x = offset[0] % period_x - period_x if tile_x else offset[0]
                        hand_y = offset[1] % period_y - period_y if tile_y else offset[1]
                        big = _expand_x(src, src_w, src_h, nx, tile_x)
                        big = _expand_y(big, src_w * nx, src_h, ny, tile_y)
                        got = reference.sample_grid(
                            src, src_w, src_h, dst_w, dst_h, rotation=rotation,
                            mirror=mirror, double=double, offset=offset, bg=bg,
                            tile=tile)
                        ref = reference.sample_grid(
                            big, src_w * nx, src_h * ny, dst_w, dst_h,
                            rotation=rotation, mirror=mirror, double=double,
                            offset=(hand_x, hand_y), bg=bg)
                        assert got == ref, (rotation, mirror, double, tile, offset)


def test_mirror_tile_seam_reflects():
    # The pixels either side of a seam are the same pixel: ... 2, 3, 3, 2 ...
    src_w, src_h = 3, 2
    grid = reference.sample_grid(_encode_src(src_w, src_h), src_w, src_h, 12, 2,
                                 offset=(0, 0), tile=(reference.MIRROR, False))
    xs = [_coord_of(px)[0] for px in grid[0]]
    assert xs == [0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0]


def test_mirror_tile_offset_is_periodic():
    # The period is twice the extent, and offsets that far apart are the same
    # frame; one extent apart is the reflected frame, so it must differ.
    src_w, src_h = 3, 2
    src = _encode_src(src_w, src_h)
    base = reference.sample_grid(src, src_w, src_h, 6, 4, offset=(1, 1),
                                 tile=reference.MIRROR)
    same = reference.sample_grid(src, src_w, src_h, 6, 4,
                                 offset=(1 - 4 * src_w, 1 + 2 * src_h),
                                 tile=reference.MIRROR)
    assert same == base
    shifted = reference.sample_grid(src, src_w, src_h, 6, 4,
                                    offset=(1 - src_w, 1), tile=reference.MIRROR)
    assert shifted != base


def test_tile_one_axis_keeps_bg_on_the_other():
    # Tiling x only: every column shows the source, rows outside its height
    # stay background.
    src_w, src_h = 3, 2
    bg = 0x0000F0
    bg_px = (0xF0, 0x00, 0x00)
    grid = reference.sample_grid(_encode_src(src_w, src_h), src_w, src_h, 6, 6,
                                 offset=(0, 2), bg=bg, tile=(True, False))
    for y in range(6):
        for x in range(6):
            if 2 <= y < 4:
                assert _coord_of(grid[y][x]) == (x % src_w, y - 2), (x, y)
            else:
                assert grid[y][x] == bg_px, (x, y)


def _all_tests():
    return [v for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]


if __name__ == "__main__":
    failures = 0
    for fn in _all_tests():
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 - script-mode reporting
            failures += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    raise SystemExit(1 if failures else 0)
