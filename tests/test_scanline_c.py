"""
Compare the compiled C++ scanline kernel against the reference.

If SPIDISPLAY_TEST_LIB points at a prebuilt shared library it is used directly.
Otherwise, when a C++ compiler is available, scanline_host.cpp is compiled on
the fly and driven through ctypes. With no library and no compiler the test
skips, so the suite stays runnable everywhere.

The kernel reads the direct source picovector was built for, chosen at compile
time by PV_PIXEL_FORMAT, so the harness is built once per format: the RGBA8888
build serves most tests, and the RGBA4444 tests at the end build the other,
SPIDISPLAY_TEST_LIB_RGBA4444 naming a prebuilt one.
"""

import ctypes
import functools
import os
import shutil
import subprocess
import tempfile

import pytest
import reference

_HERE = os.path.dirname(__file__)
_INCLUDE = os.path.join(_HERE, "..", "driver")
_SOURCE = os.path.join(_HERE, "scanline_host.cpp")

_ROTATIONS = (0, 90, 180, 270)
_SIZES = ((6, 4, 8, 6), (5, 3, 8, 4), (5, 5, 6, 6), (8, 6, 6, 4), (7, 5, 6, 4))
_FORMATS = (444, 565)
_BG = 0x0000F0
_BG_PX = (_BG & 0xff, (_BG >> 8) & 0xff, (_BG >> 16) & 0xff)


def _reduced(rgb, fmt):
    """A colour as unpack() reports it, taken from the reference packer itself.

    Hand-computing the 444 and 565 masks is the easy way to write a test that
    asserts the wrong thing, so the packer is asked instead.
    """
    return reference.unpack(reference.pack([[rgb, rgb]], 2, 1, fmt), 2, 1, fmt)[0][0]


@functools.lru_cache(maxsize=2)
def _load_library(pixel_format=1):
    """Return the ctypes handle to the kernel, or skip if it cannot be built.

    pixel_format is picovector's PV_PIXEL_FORMAT, 1 for RGBA8888 and 2 for
    RGBA4444, and the handle carries the direct source's width as pixel_bytes.
    """
    env = "SPIDISPLAY_TEST_LIB" if pixel_format == 1 else "SPIDISPLAY_TEST_LIB_RGBA4444"
    path = os.environ.get(env)
    if not path:
        compiler = (os.environ.get("CXX") or shutil.which("c++")
                    or shutil.which("g++") or shutil.which("clang++"))
        if compiler is None:
            pytest.skip("no C++ compiler and SPIDISPLAY_TEST_LIB unset")
        out_dir = tempfile.mkdtemp(prefix="spidisplay-")
        path = os.path.join(out_dir, "scanline.so")
        subprocess.run(
            [compiler, "-shared", "-fPIC", "-O2", "-std=c++17",
             f"-DPV_PIXEL_FORMAT={pixel_format}",
             "-I", _INCLUDE, "-o", path, _SOURCE],
            check=True,
        )

    common_args = [
        ctypes.POINTER(ctypes.c_uint8),  # out
        ctypes.POINTER(ctypes.c_uint8),  # src
        ctypes.c_int, ctypes.c_int, ctypes.c_int,  # src_w, src_h, src_stride
        ctypes.c_int, ctypes.c_int,  # dst_w, dst_h
        ctypes.c_int, ctypes.c_int, ctypes.c_int,  # rotation, mirror, double
        ctypes.c_uint32,  # bg
        ctypes.c_int,  # fmt
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,  # centred_x, off_x, centred_y, off_y
        ctypes.c_int, ctypes.c_int,  # tile_x, tile_y
        ctypes.POINTER(ctypes.c_uint8),  # palette, NULL for a direct source
        ctypes.c_int,  # palette_len
    ]

    lib = ctypes.CDLL(path)
    lib.pixel_bytes = 2 if pixel_format == 2 else 4
    lib.scanline_convert.restype = None
    lib.scanline_format_for_bitdepth.restype = ctypes.c_int
    lib.scanline_format_for_bitdepth.argtypes = [ctypes.c_int]
    lib.scanline_convert.argtypes = common_args
    lib.scanline_convert_cached.restype = None
    lib.scanline_convert_cached.argtypes = common_args + [
        ctypes.c_int, ctypes.c_int, ctypes.c_int,  # band_lines, cache_columns, cache_capacity
        ctypes.c_int, ctypes.c_int,  # split, slow
    ]
    return lib


# The capacity the firmware's fixed statics used to give the cache, in bytes;
# tests that model a per-display claim pass cache_columns * dst_w * 4 instead.
_DEFAULT_CAPACITY = 240 * 16 * 4


def _c_convert(lib, src, src_w, src_h, dst_w, dst_h, rotation, mirror, double, bg, fmt,
               offset=None, bands=None, capacity=_DEFAULT_CAPACITY, stride=None,
               palette=None, split=True, slow=True, tile=False):
    """Convert through the kernel, or through the banded column cache if bands is set.

    bands is a (band_lines, cache_columns) pair; capacity is the cache storage in
    bytes, modelling the per-display claim. stride is the source pitch in bytes,
    defaulting to contiguous. src is direct pixels at the width lib was built
    for, or, with palette holding up to 256 RGBA words, one index byte per
    pixel. split halves each row range the cache emits, as the
    firmware does to convert on both cores; slow says the source is reached over
    XIP, which decides both whether the cache engages and whether rows read from
    the source itself may be split. Both only apply to the banded path. tile is
    one value for both source axes or an (x, y) pair of them: False, True, or
    reference.MIRROR for repeats that alternate between normal and reversed.
    """
    out_len = (dst_w * dst_h * 3 // 2) if fmt == 444 else (dst_w * dst_h * 2)
    out = (ctypes.c_uint8 * out_len)()
    buf = (ctypes.c_uint8 * len(src)).from_buffer_copy(src)
    ox, oy = (None, None) if offset is None else offset
    if not isinstance(tile, (tuple, list)):
        tile = (tile, tile)
    src_bytes = lib.pixel_bytes if palette is None else 1
    pal = None if palette is None else (ctypes.c_uint8 * len(palette)).from_buffer_copy(palette)
    args = (out, buf, src_w, src_h, src_w * src_bytes if stride is None else stride,
            dst_w, dst_h,
            rotation, int(bool(mirror)), int(bool(double)), bg, fmt,
            1 if ox is None else 0, 0 if ox is None else ox,
            1 if oy is None else 0, 0 if oy is None else oy,
            int(tile[0]), int(tile[1]),
            pal, 0 if palette is None else len(palette))
    if bands is None:
        lib.scanline_convert(*args)
    else:
        lib.scanline_convert_cached(*args, *bands, capacity,
                                    int(bool(split)), int(bool(slow)))
    return bytes(out)


def _split_variants(lib, *args, **kwargs):
    """Convert every split and source-speed combination, which must all agree.

    The split hands half of a row range to the other core on device, and only
    ranges reading SRAM are eligible: a cached window always is, the source
    itself only when it is not the slow one. Running both source speeds covers
    the split on either descriptor, and a slow source is also what engages the
    cache, so the four together are the firmware's whole matrix. The first is
    returned for the caller to compare with the reference.
    """
    results = [_c_convert(lib, *args, split=split, slow=slow, **kwargs)
               for split in (True, False) for slow in (True, False)]
    for i, other in enumerate(results[1:], start=1):
        assert results[0] == other, \
            f"split/slow combination {i} changed the output: {args[1:]} {kwargs}"
    return results[0]


def test_c_matches_reference():
    lib = _load_library()
    for src_w, src_h, dst_w, dst_h in _SIZES:
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS:
                        ref = reference.convert(
                            src, src_w, src_h, dst_w, dst_h,
                            rotation=rotation, mirror=mirror, double=double,
                            bg=_BG, fmt=fmt,
                        )
                        got = _c_convert(
                            lib, src, src_w, src_h, dst_w, dst_h,
                            rotation, mirror, double, _BG, fmt,
                        )
                        assert got == ref, (src_w, src_h, dst_w, dst_h,
                                            rotation, mirror, double, fmt)


def test_c_matches_reference_offsets():
    lib = _load_library()
    # Full pairs plus per-axis None (centre just that axis).
    offsets = ((0, 0), (2, 1), (-1, -2), (3, 0), (-3, -3),
               (None, 2), (2, None), (None, None))
    for src_w, src_h, dst_w, dst_h in ((6, 4, 8, 6), (5, 3, 8, 6)):
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in _ROTATIONS:
            for offset in offsets:
                for fmt in _FORMATS:
                    ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                            rotation=rotation, offset=offset,
                                            bg=_BG, fmt=fmt)
                    got = _c_convert(lib, src, src_w, src_h, dst_w, dst_h,
                                     rotation, False, False, _BG, fmt, offset=offset)
                    assert got == ref, (src_w, src_h, rotation, offset, fmt)


def test_c_matches_reference_strided():
    # Cells of a wider strip: the source pitch exceeds the cell's width * 4, as
    # a spritesheet frame's does. Odd cell widths exercise the RGB444 pairing;
    # the last cell's slice ends exactly at the extent the pitch implies.
    lib = _load_library()
    strip_w, cell_h = 40, 12
    strip = bytes(((i * 37 + 11) & 0xff) for i in range(strip_w * cell_h * 4))
    stride = strip_w * 4
    for cell_x, cell_w in ((0, 13), (13, 13), (27, 13), (9, 8)):
        src = strip[cell_x * 4:]
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS:
                        ref = reference.convert(
                            src, cell_w, cell_h, 16, 12,
                            rotation=rotation, mirror=mirror, double=double,
                            bg=_BG, fmt=fmt, stride=stride,
                        )
                        got = _c_convert(
                            lib, src, cell_w, cell_h, 16, 12,
                            rotation, mirror, double, _BG, fmt, stride=stride,
                        )
                        assert got == ref, (cell_x, cell_w, rotation,
                                            mirror, double, fmt)


def test_c_matches_reference_strided_offsets():
    # A strided cell placed off-centre, clipping each edge in turn.
    lib = _load_library()
    strip_w, cell_h = 40, 12
    strip = bytes(((i * 37 + 11) & 0xff) for i in range(strip_w * cell_h * 4))
    stride = strip_w * 4
    src = strip[13 * 4:]
    offsets = ((-5, 0), (0, -5), (12, 0), (0, 9), (None, 3), (3, None))
    for rotation in _ROTATIONS:
        for offset in offsets:
            for fmt in _FORMATS:
                ref = reference.convert(src, 13, cell_h, 16, 12,
                                        rotation=rotation, offset=offset,
                                        bg=_BG, fmt=fmt, stride=stride)
                got = _c_convert(lib, src, 13, cell_h, 16, 12,
                                 rotation, False, False, _BG, fmt,
                                 offset=offset, stride=stride)
                assert got == ref, (rotation, offset, fmt)


# Fully opaque, so the geometry tests below compare the indexed and the direct
# path on equal terms; the composite gets its own cases.
_PALETTE = bytes(0xff if i % 4 == 3 else ((i * 37 + 11) & 0xff) for i in range(1024))

def _premultiplied(alpha_of):
    """A palette whose colour is scaled by its own alpha, as picovector stores it."""
    out = bytearray()
    for entry in range(256):
        alpha = alpha_of(entry)
        for channel in range(3):
            colour = ((entry * 4 + channel) * 37 + 11) & 0xff
            out.append(colour * alpha // 255)
        out.append(alpha)
    return bytes(out)


# Alpha as a real image supplies it: a transparent entry, a translucent one and
# opaque ones, cycling so every geometry meets all three.
_PALETTE_ALPHA = _premultiplied(
    lambda entry: (0x00, 0x80, 0xff, 0x40, 0xff)[entry % 5])


def test_c_matches_reference_indexed():
    # The equivalence that makes the indexed path safe: with an opaque palette,
    # the same picture as indices-plus-palette and as expanded RGBA must convert
    # identically, and both must match the reference. Odd widths exercise the
    # RGB444 pairing.
    lib = _load_library()
    for src_w, src_h, dst_w, dst_h in ((6, 4, 8, 6), (5, 3, 8, 4), (7, 5, 6, 4)):
        idx = bytes(((i * 29 + 3) & 0xff) for i in range(src_w * src_h))
        rgba = b"".join(_PALETTE[i * 4:i * 4 + 4] for i in idx)
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS:
                        ref = reference.convert(
                            idx, src_w, src_h, dst_w, dst_h,
                            rotation=rotation, mirror=mirror, double=double,
                            bg=_BG, fmt=fmt, palette=_PALETTE,
                        )
                        got = _c_convert(
                            lib, idx, src_w, src_h, dst_w, dst_h,
                            rotation, mirror, double, _BG, fmt, palette=_PALETTE,
                        )
                        assert got == ref, (src_w, src_h, rotation,
                                            mirror, double, fmt)
                        expanded = _c_convert(
                            lib, rgba, src_w, src_h, dst_w, dst_h,
                            rotation, mirror, double, _BG, fmt,
                        )
                        assert got == expanded, (src_w, src_h, rotation,
                                                 mirror, double, fmt)


def test_indexed_palette_composites_over_background():
    # A palette carrying transparent, translucent and opaque entries, through
    # every geometry the kernel has: the composite happens in the table, so it
    # must survive rotation, mirroring, pixel-doubling and both packers.
    lib = _load_library()
    for src_w, src_h, dst_w, dst_h in ((6, 4, 8, 6), (7, 5, 6, 4)):
        idx = bytes(((i * 29 + 3) & 0xff) for i in range(src_w * src_h))
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS:
                        ref = reference.convert(
                            idx, src_w, src_h, dst_w, dst_h,
                            rotation=rotation, mirror=mirror, double=double,
                            bg=_BG, fmt=fmt, palette=_PALETTE_ALPHA,
                        )
                        got = _c_convert(
                            lib, idx, src_w, src_h, dst_w, dst_h,
                            rotation, mirror, double, _BG, fmt,
                            palette=_PALETTE_ALPHA,
                        )
                        assert got == ref, (src_w, src_h, rotation,
                                            mirror, double, fmt)


def test_indexed_endpoints_are_exact():
    # The composite's endpoints, checked without the reference: an opaque entry
    # passes through whatever the background is, and a transparent one gives
    # exactly the background.
    lib = _load_library()
    src_w, src_h, dst_w, dst_h = 8, 6, 6, 4   # covers the panel at every rotation
    idx = bytes(((i * 29 + 3) & 0xff) for i in range(src_w * src_h))
    opaque = _premultiplied(lambda _entry: 0xff)
    clear = _premultiplied(lambda _entry: 0x00)
    for rotation in _ROTATIONS:
        for fmt in _FORMATS:
            on_black = _c_convert(lib, idx, src_w, src_h, dst_w, dst_h,
                                  rotation, False, False, 0x000000, fmt,
                                  palette=opaque)
            on_white = _c_convert(lib, idx, src_w, src_h, dst_w, dst_h,
                                  rotation, False, False, 0xFFFFFF, fmt,
                                  palette=opaque)
            assert on_black == on_white, (rotation, fmt)

            got = _c_convert(lib, idx, src_w, src_h, dst_w, dst_h,
                             rotation, False, False, _BG, fmt, palette=clear)
            grid = reference.unpack(got, dst_w, dst_h, fmt)
            assert all(px == _reduced(_BG_PX, fmt) for row in grid for px in row), (rotation, fmt)


def test_indexed_overbright_entry_is_clamped():
    # A hand-built table can claim more colour than its alpha allows, which the
    # premultiplied composite would otherwise let wrap. Every channel saturates
    # instead, and C and the reference agree on that.
    lib = _load_library()
    src_w, src_h, dst_w, dst_h = 6, 4, 8, 6
    idx = bytes(((i * 29 + 3) & 0xff) for i in range(src_w * src_h))
    overbright = bytes(0x20 if i % 4 == 3 else 0xff for i in range(1024))
    for fmt in _FORMATS:
        ref = reference.convert(idx, src_w, src_h, dst_w, dst_h,
                                bg=0xFFFFFF, fmt=fmt, palette=overbright)
        got = _c_convert(lib, idx, src_w, src_h, dst_w, dst_h,
                         0, False, False, 0xFFFFFF, fmt, palette=overbright)
        assert got == ref, fmt
        grid = reference.unpack(got, dst_w, dst_h, fmt)
        assert all(px == _reduced((255, 255, 255), fmt)
                   for row in grid for px in row), fmt


def test_indexed_short_palette_tail_is_transparent():
    # An index byte reaching past the entries the source supplied lands in the
    # table's zeroed tail, which reads as transparent and so takes the
    # background. Pins the clamp and zero-fill in prepare_palette().
    lib = _load_library()
    src_w, src_h, dst_w, dst_h = 6, 4, 8, 6
    palette = _PALETTE_ALPHA[:64]   # 16 entries; most indices fall in the tail
    idx = bytes(((i * 29 + 3) & 0xff) for i in range(src_w * src_h))
    for rotation in _ROTATIONS:
        for fmt in _FORMATS:
            ref = reference.convert(idx, src_w, src_h, dst_w, dst_h,
                                    rotation=rotation, bg=_BG, fmt=fmt,
                                    palette=palette)
            got = _c_convert(lib, idx, src_w, src_h, dst_w, dst_h,
                             rotation, False, False, _BG, fmt, palette=palette)
            assert got == ref, (rotation, fmt)

    # Every index in the tail, so the whole frame is background.
    tail = bytes([200]) * (src_w * src_h)
    for fmt in _FORMATS:
        got = _c_convert(lib, tail, src_w, src_h, dst_w, dst_h,
                         0, False, False, _BG, fmt, palette=palette)
        grid = reference.unpack(got, dst_w, dst_h, fmt)
        assert all(px == _reduced(_BG_PX, fmt) for row in grid for px in row), fmt


def test_rgba_alpha_is_ignored():
    # An RGBA source's alpha byte does not reach the conversion: a per-pixel
    # blend was measured too expensive (see scanline.hpp), so the same colour
    # bytes convert the same whatever their alpha says and whatever the
    # background is.
    lib = _load_library()
    src_w, src_h, dst_w, dst_h = 8, 6, 6, 4
    colours = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
    opaque = bytes(0xff if i % 4 == 3 else colours[i] for i in range(len(colours)))
    clear = bytes(0x00 if i % 4 == 3 else colours[i] for i in range(len(colours)))
    for rotation in _ROTATIONS:
        for fmt in _FORMATS:
            for double in (False, True):
                got = _c_convert(lib, opaque, src_w, src_h, dst_w, dst_h,
                                 rotation, False, double, _BG, fmt)
                same = _c_convert(lib, clear, src_w, src_h, dst_w, dst_h,
                                  rotation, False, double, 0xFFFFFF, fmt)
                assert got == same, (rotation, fmt, double)


def test_c_matches_reference_indexed_strided():
    # An indexed cell of a wider strip: one index byte per pixel, so the pitch
    # is the strip's width in bytes. Offsets clip each edge in turn.
    lib = _load_library()
    strip_w, cell_h = 40, 12
    strip = bytes(((i * 29 + 3) & 0xff) for i in range(strip_w * cell_h))
    offsets = (None, (-5, 0), (0, -5), (12, 0), (0, 9))
    for cell_x, cell_w in ((0, 13), (13, 13), (27, 13)):
        src = strip[cell_x:]
        for rotation in _ROTATIONS:
            for offset in offsets:
                for fmt in _FORMATS:
                    ref = reference.convert(src, cell_w, cell_h, 16, 12,
                                            rotation=rotation, offset=offset,
                                            bg=_BG, fmt=fmt, stride=strip_w,
                                            palette=_PALETTE)
                    got = _c_convert(lib, src, cell_w, cell_h, 16, 12,
                                     rotation, False, False, _BG, fmt,
                                     offset=offset, stride=strip_w,
                                     palette=_PALETTE)
                    assert got == ref, (cell_x, rotation, offset, fmt)


def test_cached_matches_reference_indexed():
    # Indexed cells through the banded column cache: the windows hold one byte
    # per pixel, so this proves the byte-sized fill and capacity accounting.
    lib = _load_library()
    cell_w, cell_h = 48, 72
    strip_w = cell_w * 3
    strip = bytes(((i * 29 + 3) & 0xff) for i in range(strip_w * cell_h))
    variants = ((False, False, 565), (True, False, 565),
                (False, True, 444), (True, True, 444))
    for cell_x in (0, cell_w, cell_w * 2):
        src = strip[cell_x:]
        for rotation in _ROTATIONS:
            for mirror, double, fmt in variants:
                ref = reference.convert(src, cell_w, cell_h, 64, 96,
                                        rotation=rotation, mirror=mirror,
                                        double=double, bg=_BG, fmt=fmt,
                                        stride=strip_w, palette=_PALETTE)
                for bands in ((16, 16), (16, 4), (5, 16), (16, 2)):
                    got = _split_variants(lib, src, cell_w, cell_h, 64, 96,
                                       rotation, mirror, double, _BG, fmt,
                                       bands=bands, stride=strip_w,
                                       palette=_PALETTE)
                    assert got == ref, (cell_x, rotation, mirror, double,
                                        fmt, bands)


def test_cached_matches_reference():
    # The column cache only engages at 90/270; the other rotations prove it hands
    # them through untouched. Sources both larger and smaller than the panel, so
    # both a fully covered frame and a background-padded one are cached. Narrow
    # widths 1-3 are live windows now that no minimum column threshold exists.
    lib = _load_library()
    sizes = ((100, 140, 64, 96), (48, 72, 64, 96), (17, 9, 64, 96),
             (63, 97, 64, 96), (5, 5, 64, 96))
    for src_w, src_h, dst_w, dst_h in sizes:
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in _ROTATIONS:
            for double in (False, True):
                ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                        rotation=rotation, double=double,
                                        bg=_BG, fmt=565)
                for bands in ((16, 16), (16, 4), (5, 16), (1, 16), (16, 0),
                              (16, 1), (16, 2), (16, 3)):
                    got = _split_variants(lib, src, src_w, src_h, dst_w, dst_h,
                                       rotation, False, double, _BG, 565, bands=bands)
                    assert got == ref, (src_w, src_h, rotation, double, bands)


def test_cached_matches_reference_offsets():
    # An offset source pads with background on the leading edge, so a cache
    # window can straddle the boundary between padding and source.
    lib = _load_library()
    offsets = ((0, 0), (7, 3), (-9, -5), (40, 60), (-40, -60), (None, 5), (5, None))
    # (mirror, double, fmt): both source strides, both packers, both walk phases.
    variants = ((False, False, 565), (True, False, 565), (False, True, 565),
                (True, True, 565), (False, False, 444), (True, True, 444))
    for src_w, src_h, dst_w, dst_h in ((48, 72, 64, 96), (100, 140, 64, 96)):
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in (90, 270):
            for offset in offsets:
                for mirror, double, fmt in variants:
                    ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                            rotation=rotation, mirror=mirror,
                                            double=double, offset=offset, bg=_BG, fmt=fmt)
                    got = _split_variants(lib, src, src_w, src_h, dst_w, dst_h,
                                       rotation, mirror, double, _BG, fmt,
                                       offset=offset, bands=(16, 16))
                    assert got == ref, (src_w, src_h, rotation, offset,
                                        mirror, double, fmt)


def test_cached_matches_reference_strided():
    # Strided cells through the banded column cache: fill() walks the parent's
    # pitch while the window it builds stays contiguous. The last cell's slice
    # ends exactly at the extent the pitch implies.
    lib = _load_library()
    cell_w, cell_h = 48, 72
    strip_w = cell_w * 3
    strip = bytes(((i * 37 + 11) & 0xff) for i in range(strip_w * cell_h * 4))
    stride = strip_w * 4
    variants = ((False, False, 565), (True, False, 565),
                (False, True, 444), (True, True, 444))
    for cell_x in (0, cell_w, cell_w * 2):
        src = strip[cell_x * 4:]
        for rotation in _ROTATIONS:
            for mirror, double, fmt in variants:
                ref = reference.convert(src, cell_w, cell_h, 64, 96,
                                        rotation=rotation, mirror=mirror,
                                        double=double, bg=_BG, fmt=fmt, stride=stride)
                for bands in ((16, 16), (16, 4), (5, 16), (16, 2)):
                    got = _split_variants(lib, src, cell_w, cell_h, 64, 96,
                                       rotation, mirror, double, _BG, fmt,
                                       bands=bands, stride=stride)
                    assert got == ref, (cell_x, rotation, mirror, double,
                                        fmt, bands)


def test_cached_matches_reference_panel():
    # Panel-sized frames: a 240-wide destination fills the cache's row budget
    # exactly, and a 320-wide one overruns it and must fall back per window.
    lib = _load_library()
    for src_w, src_h, dst_w, dst_h in ((300, 400, 240, 320), (200, 260, 240, 320),
                                       (400, 300, 320, 240), (260, 200, 320, 240)):
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in (90, 270):
            for fmt in _FORMATS:
                ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                        rotation=rotation, bg=_BG, fmt=fmt)
                got = _split_variants(lib, src, src_w, src_h, dst_w, dst_h,
                                   rotation, False, False, _BG, fmt, bands=(16, 16))
                assert got == ref, (src_w, src_h, dst_w, dst_h, rotation, fmt)


def test_c_matches_reference_large():
    # Sources larger than a real panel (240x320), even/odd, both orientations.
    # The other tests only cover small sizes, where an int-width or large-offset
    # divergence between C and reference could hide.
    lib = _load_library()
    for src_w, src_h, dst_w, dst_h in ((300, 400, 240, 320), (400, 300, 240, 320),
                                       (341, 401, 240, 320), (260, 340, 240, 320)):
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in _ROTATIONS:
            for fmt in _FORMATS:
                ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                        rotation=rotation, bg=_BG, fmt=fmt)
                got = _c_convert(lib, src, src_w, src_h, dst_w, dst_h,
                                 rotation, False, False, _BG, fmt)
                assert got == ref, (src_w, src_h, rotation, fmt)


def test_c_matches_reference_tiled():
    # The direct path with a tiled read: each axis alone and both together,
    # sources smaller than, straddling and larger than the panel in the tiled
    # axis, and offsets negative, mid-period and beyond one period, all of
    # which tiling makes valid.
    lib = _load_library()
    sizes = ((6, 4, 8, 6), (5, 3, 8, 4), (12, 9, 8, 6))
    offsets = ((0, 0), (2, 1), (-5, -7), (23, 31))
    for src_w, src_h, dst_w, dst_h in sizes:
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS:
                        for tile in ((True, False), (False, True), (True, True),
                                     (2, False), (False, 2), (2, 2), (2, True)):
                            for offset in offsets:
                                ref = reference.convert(
                                    src, src_w, src_h, dst_w, dst_h,
                                    rotation=rotation, mirror=mirror, double=double,
                                    offset=offset, bg=_BG, fmt=fmt, tile=tile,
                                )
                                got = _c_convert(
                                    lib, src, src_w, src_h, dst_w, dst_h,
                                    rotation, mirror, double, _BG, fmt,
                                    offset=offset, tile=tile,
                                )
                                assert got == ref, (src_w, src_h, rotation, mirror,
                                                    double, fmt, tile, offset)


def test_c_tiled_seams_at_odd_pair_positions():
    # An odd source width tiled across an RGB444 row puts a seam inside a
    # packed pair every other repeat, so one pair reads its two pixels from
    # different repeats of the source.
    lib = _load_library()
    for src_w in (3, 5, 7):
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * 4 * 4))
        for mode in (True, 2):
            for mirror in (False, True):
                for offset in ((0, 0), (1, 0), (-4, 0)):
                    ref = reference.convert(src, src_w, 4, 16, 4, mirror=mirror,
                                            offset=offset, bg=_BG, fmt=444,
                                            tile=(mode, False))
                    got = _c_convert(lib, src, src_w, 4, 16, 4, 0, mirror, False,
                                     _BG, 444, offset=offset, tile=(mode, False))
                    assert got == ref, (src_w, mode, mirror, offset)


def test_c_matches_reference_tiled_indexed_strided():
    # A tiled read over an indexed, strided cell: the two source layouts the
    # shipped art uses, with the seam arithmetic on top of the parent pitch.
    lib = _load_library()
    cell_w, cell_h = 5, 4
    strip_w = cell_w * 3
    strip = bytes(((i * 29 + 3) & 0xff) for i in range(strip_w * cell_h))
    src = strip[cell_w:]
    for rotation in _ROTATIONS:
        for fmt in _FORMATS:
            for tile in ((True, False), (True, True), (2, False), (2, 2)):
                ref = reference.convert(src, cell_w, cell_h, 8, 6,
                                        rotation=rotation, offset=(-3, 2), bg=_BG,
                                        fmt=fmt, stride=strip_w, palette=_PALETTE_ALPHA,
                                        tile=tile)
                got = _c_convert(lib, src, cell_w, cell_h, 8, 6, rotation, False,
                                 False, _BG, fmt, offset=(-3, 2), stride=strip_w,
                                 palette=_PALETTE_ALPHA, tile=tile)
                assert got == ref, (rotation, fmt, tile)


def test_cached_matches_reference_tiled():
    # The banded column cache with a tiled read at 90/270: a window straddling
    # the source's end, a window wider than the source from a small tile, the
    # whole-source window a tiled within-row walk needs, and a capacity too
    # small for it, which falls back to converting from the source.
    lib = _load_library()
    sizes = ((48, 72, 64, 96), (17, 9, 64, 96), (5, 5, 64, 96), (100, 140, 64, 96))
    offsets = ((0, 0), (-9, 13), (200, -333))
    variants = ((False, False, 565), (True, False, 444), (False, True, 565),
                (True, True, 444))
    for src_w, src_h, dst_w, dst_h in sizes:
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in (90, 270):
            for tile in ((True, False), (False, True), (True, True),
                         (2, False), (False, 2), (2, 2)):
                for offset in offsets:
                    for mirror, double, fmt in variants:
                        ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                                rotation=rotation, mirror=mirror,
                                                double=double, offset=offset,
                                                bg=_BG, fmt=fmt, tile=tile)
                        for bands in ((16, 16), (16, 4), (5, 16)):
                            got = _split_variants(lib, src, src_w, src_h,
                                                  dst_w, dst_h, rotation, mirror,
                                                  double, _BG, fmt, offset=offset,
                                                  bands=bands, tile=tile)
                            assert got == ref, (src_w, src_h, rotation, tile,
                                                offset, mirror, double, fmt, bands)


def test_c_matches_reference_tiled_tiny():
    # The degenerate tiles: 1x1 repaints one pixel everywhere, and 1xN / Nx1
    # make the seam land on every step of one axis. The cache's window is far
    # wider than these sources, so its repeat loop runs many runs per row.
    lib = _load_library()
    for src_w, src_h in ((1, 1), (1, 3), (3, 1)):
        src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS:
                        for offset in ((0, 0), (-7, 13)):
                            ref = reference.convert(src, src_w, src_h, 8, 6,
                                                    rotation=rotation, mirror=mirror,
                                                    double=double, offset=offset,
                                                    bg=_BG, fmt=fmt, tile=True)
                            got = _c_convert(lib, src, src_w, src_h, 8, 6, rotation,
                                             mirror, double, _BG, fmt, offset=offset,
                                             tile=True)
                            assert got == ref, (src_w, src_h, rotation, mirror,
                                                double, fmt, offset)
        for rotation in (90, 270):
            ref = reference.convert(src, src_w, src_h, 64, 96, rotation=rotation,
                                    offset=(-7, 13), bg=_BG, fmt=565, tile=True)
            got = _split_variants(lib, src, src_w, src_h, 64, 96, rotation,
                                  False, False, _BG, 565, offset=(-7, 13),
                                  bands=(16, 16), tile=True)
            assert got == ref, (src_w, src_h, rotation)


# The machine-word extremes the binding can pass through, and values close
# enough to them that a subtraction before any reduction would overflow.
_EXTREME_OFFSETS = (
    (2**31 - 1, 2**31 - 1), (-2**31, -2**31), (2**31 - 1, -2**31),
    (-2**31 + 1, 2**31 - 2), (2**30, -2**30),
)


def test_offset_extremes_match_reference():
    # Offsets at the edges of the machine word, tiled and not. The oracle
    # computes in Python's own integers, so a C overflow shows as a mismatch;
    # the UBSan build catches ones that happen to wrap to the right answer.
    lib = _load_library()
    src = bytes(((i * 37 + 11) & 0xff) for i in range(6 * 4 * 4))
    for rotation in _ROTATIONS:
        for mirror in (False, True):
            for double in (False, True):
                for tile in (False, (True, False), (True, True), (2, 2)):
                    for offset in _EXTREME_OFFSETS:
                        ref = reference.convert(src, 6, 4, 8, 6,
                                                rotation=rotation, mirror=mirror,
                                                double=double, offset=offset,
                                                bg=_BG, fmt=565, tile=tile)
                        got = _c_convert(lib, src, 6, 4, 8, 6, rotation, mirror,
                                         double, _BG, 565, offset=offset,
                                         tile=tile)
                        assert got == ref, (rotation, mirror, double, tile, offset)


def test_offset_extremes_match_reference_cached():
    lib = _load_library()
    src = bytes(((i * 37 + 11) & 0xff) for i in range(48 * 72 * 4))
    for rotation in (90, 270):
        for tile in (False, (True, False), (True, True), (2, 2)):
            for offset in _EXTREME_OFFSETS:
                ref = reference.convert(src, 48, 72, 64, 96, rotation=rotation,
                                        offset=offset, bg=_BG, fmt=565, tile=tile)
                got = _split_variants(lib, src, 48, 72, 64, 96, rotation, False,
                                      False, _BG, 565, offset=offset,
                                      bands=(16, 16), tile=tile)
                assert got == ref, (rotation, tile, offset)


def test_cached_tiled_capacity_fallback():
    # A capacity below one window's need makes every fill() refuse, so a tiled
    # frame converts from the source per window and must still match.
    lib = _load_library()
    src_w, src_h = 48, 72
    src = bytes(((i * 37 + 11) & 0xff) for i in range(src_w * src_h * 4))
    for rotation in (90, 270):
        for tile in ((True, False), (False, True), (True, True), (2, 2)):
            ref = reference.convert(src, src_w, src_h, 64, 96, rotation=rotation,
                                    offset=(-7, 5), bg=_BG, fmt=565, tile=tile)
            got = _split_variants(lib, src, src_w, src_h, 64, 96, rotation,
                                  False, False, _BG, 565, offset=(-7, 5),
                                  bands=(16, 16), capacity=64, tile=tile)
            assert got == ref, (rotation, tile)


# The RGBA4444 build. Its loader expands each nibble by 17, so a source converts
# as its RGBA8888 expansion would, and the tests below hold it to that through
# the reference, through the RGBA8888 build, and through the palette path, which
# the format does not touch. That build converts to RGB444 alone, RGB565 carrying
# no more of a four-bit channel for a third more bytes, so its packer is left out.

_FORMATS_4444 = (444,)


def _rgba4444_source(src_w, src_h):
    """A 4444 source whose two bytes a pixel run through every nibble."""
    return bytes(((i * 53 + 7) & 0xff) for i in range(src_w * src_h * 2))


def test_rgba4444_matches_reference():
    lib = _load_library(pixel_format=2)
    for src_w, src_h, dst_w, dst_h in _SIZES:
        src = _rgba4444_source(src_w, src_h)
        for rotation in _ROTATIONS:
            for mirror in (False, True):
                for double in (False, True):
                    for fmt in _FORMATS_4444:
                        ref = reference.convert(
                            src, src_w, src_h, dst_w, dst_h,
                            rotation=rotation, mirror=mirror, double=double,
                            bg=_BG, fmt=fmt, src_format=4444,
                        )
                        got = _c_convert(
                            lib, src, src_w, src_h, dst_w, dst_h,
                            rotation, mirror, double, _BG, fmt,
                        )
                        assert got == ref, (src_w, src_h, dst_w, dst_h,
                                            rotation, mirror, double, fmt)


def test_rgba4444_matches_expanded_rgba8888():
    # The two builds agree: a 4444 source through one is its expansion through
    # the other, so every geometry the RGBA8888 tests cover carries across.
    lib4444 = _load_library(pixel_format=2)
    lib8888 = _load_library()
    offsets = ((None, None), (2, 1), (-3, -3), (None, 2))
    for src_w, src_h, dst_w, dst_h in _SIZES:
        src = _rgba4444_source(src_w, src_h)
        expanded = reference.expand_rgba4444(src)
        for rotation in _ROTATIONS:
            for offset in offsets:
                for tile in (False, True, reference.MIRROR):
                    for fmt in _FORMATS_4444:
                        got = _c_convert(lib4444, src, src_w, src_h, dst_w, dst_h,
                                         rotation, False, False, _BG, fmt,
                                         offset=offset, tile=tile)
                        want = _c_convert(lib8888, expanded, src_w, src_h, dst_w, dst_h,
                                          rotation, False, False, _BG, fmt,
                                          offset=offset, tile=tile)
                        assert got == want, (src_w, src_h, rotation, offset, tile, fmt)


def test_rgba4444_matches_reference_strided():
    # Cells of a wider strip at two bytes a pixel, the pitch the binding checks
    # against the compiled width.
    lib = _load_library(pixel_format=2)
    strip_w, cell_h = 40, 12
    strip = _rgba4444_source(strip_w, cell_h)
    stride = strip_w * 2
    for cell_x, cell_w in ((0, 13), (13, 13), (27, 13), (9, 8)):
        src = strip[cell_x * 2:]
        for rotation in _ROTATIONS:
            for double in (False, True):
                for fmt in _FORMATS_4444:
                    ref = reference.convert(src, cell_w, cell_h, 16, 12,
                                            rotation=rotation, double=double,
                                            bg=_BG, fmt=fmt, stride=stride,
                                            src_format=4444)
                    got = _c_convert(lib, src, cell_w, cell_h, 16, 12,
                                     rotation, False, double, _BG, fmt, stride=stride)
                    assert got == ref, (cell_x, cell_w, rotation, double, fmt)


def test_rgba4444_cached_matches_reference():
    # The column cache sizes its windows from the descriptor's pixel width, so
    # at two bytes a window holds twice the columns for the same claim.
    lib = _load_library(pixel_format=2)
    sizes = ((100, 140, 64, 96), (48, 72, 64, 96), (17, 9, 64, 96), (5, 5, 64, 96))
    for src_w, src_h, dst_w, dst_h in sizes:
        src = _rgba4444_source(src_w, src_h)
        for rotation in _ROTATIONS:
            for double in (False, True):
                for fmt in _FORMATS_4444:
                    ref = reference.convert(src, src_w, src_h, dst_w, dst_h,
                                            rotation=rotation, double=double,
                                            bg=_BG, fmt=fmt, src_format=4444)
                    for bands in ((16, 16), (16, 4), (5, 16), (1, 16), (16, 0), (16, 1)):
                        got = _split_variants(lib, src, src_w, src_h, dst_w, dst_h,
                                              rotation, False, double, _BG, fmt,
                                              bands=bands)
                        assert got == ref, (src_w, src_h, rotation, double, fmt, bands)


def test_rgba4444_through_rgb444_is_exact():
    # RGB444 keeps the top nibble of each expanded channel, which is the stored
    # nibble again, so every one of the 4096 colours reaches the panel unchanged.
    lib = _load_library(pixel_format=2)
    src_w, src_h = 64, 64
    src = bytearray()
    for colour in range(4096):
        r, g, b = colour & 0xf, (colour >> 4) & 0xf, colour >> 8
        src += bytes(((g << 4) | r, (0xf << 4) | b))
    got = _c_convert(lib, bytes(src), src_w, src_h, src_w, src_h,
                     0, False, False, _BG, 444)
    expected = bytearray()
    for colour in range(0, 4096, 2):
        r0, g0, b0 = colour & 0xf, (colour >> 4) & 0xf, colour >> 8
        r1, g1, b1 = (colour + 1) & 0xf, ((colour + 1) >> 4) & 0xf, (colour + 1) >> 8
        expected += bytes(((r0 << 4) | g0, (b0 << 4) | r1, (g1 << 4) | b1))
    assert got == bytes(expected)


def test_rgba4444_build_indexed_matches_reference():
    # The palette stays RGBA8888 words in either build, so an indexed source
    # converts identically through both and through the reference.
    lib4444 = _load_library(pixel_format=2)
    lib8888 = _load_library()
    for src_w, src_h, dst_w, dst_h in ((6, 4, 8, 6), (5, 3, 8, 4), (7, 5, 6, 4)):
        idx = bytes(((i * 29 + 3) & 0xff) for i in range(src_w * src_h))
        for rotation in _ROTATIONS:
            for double in (False, True):
                for fmt in _FORMATS_4444:
                    ref = reference.convert(idx, src_w, src_h, dst_w, dst_h,
                                            rotation=rotation, double=double,
                                            bg=_BG, fmt=fmt, palette=_PALETTE_ALPHA)
                    got = _c_convert(lib4444, idx, src_w, src_h, dst_w, dst_h,
                                     rotation, False, double, _BG, fmt,
                                     palette=_PALETTE_ALPHA)
                    same = _c_convert(lib8888, idx, src_w, src_h, dst_w, dst_h,
                                      rotation, False, double, _BG, fmt,
                                      palette=_PALETTE_ALPHA)
                    assert got == ref == same, (src_w, src_h, rotation, double, fmt)


def test_rgba4444_build_has_no_rgb565():
    # The packer for a depth the build left out is refused, which the binding turns
    # into its bitdepth error, and the RGBA8888 build keeps both
    lib4444 = _load_library(pixel_format=2)
    lib8888 = _load_library()
    assert lib4444.scanline_format_for_bitdepth(12) == 444
    assert lib4444.scanline_format_for_bitdepth(16) == 0
    assert lib8888.scanline_format_for_bitdepth(12) == 444
    assert lib8888.scanline_format_for_bitdepth(16) == 565
