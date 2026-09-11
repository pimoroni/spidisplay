# SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# Measures what the second core buys frame conversion. Only rows reading SRAM are split,
# meaning a canvas or a source read through the column cache, since two cores reading
# PSRAM over one QMI cost more than the halved pixel work saves. Each case says whether
# it expects the split, so a wrong answer either way is named.
#
# spidisplay.dual_convert() runs each case both ways over the same pixels, and core1_rows
# proves the split engaged. The setting survives a soft reset, so it is restored however
# the run ends. v_sync is off, leaving the timings conversion and the wire alone.

import gc

import ports
import spidisplay
from picovector import color, image, mat3, shape
from screens import Screen154, Screen280
from ports import ScreenPort
from spce import SPCE_A_PINS

SCREEN = Screen154              # The panel type to drive, which SP/CE A must carry
SETTINGS = ((2, 0), (12, 12))   # The (band_lines, cache_columns) pairs to compare
WARMUP_FRAMES = 2
MEASURE_FRAMES = 8

# The 1.60x an SRAM source reaches on unrotated 12-bit rows, which driver/scanline.hpp
# records against the cache's own figure
SRAM_FLOOR = 1.6

# What a cached PSRAM window has to reach, set below the SRAM figure since the cache
# fills from PSRAM before either core reads it
CACHED_FLOOR = 1.1

DECLINE_TOLERANCE = 0.97        # A declined case at or below this lost time

BITS_PER_BYTE = 8

assert SCREEN in (Screen154, Screen280)


def draw(canvas):
    """Draw content with enough colour variety that no packer path is trivial."""
    canvas.pen = color.black
    canvas.clear()
    line = shape.line(40, 0, 0, 120, 2)
    for i in range(0, 360, 15):
        canvas.pen = color.hsv(((i * 255) // 360) % 256, 255, 255)
        line.transform = mat3().translate(canvas.width / 2, canvas.height / 2).rotate(i)
        canvas.shape(line)


def splits(source_name, rotation, cache_columns):
    """Whether these rows read SRAM, which is what decides a split.

    A canvas always does. A PSRAM source only does through a cache window, which
    needs both a rotation that strides by whole source rows and columns to cache.
    """
    if source_name == "SRAM":
        return True
    return rotation in (90, 270) and cache_columns >= 1


def measure(screen, source, rotation, dual):
    """Average convert time a row, core1's share of it, and the frame and stall times.

    All four averaged over MEASURE_FRAMES.
    """
    spidisplay.dual_convert(dual)
    for _ in range(WARMUP_FRAMES):
        screen.update(source, rotation=rotation)

    convert = core1 = frame = stall = 0
    for _ in range(MEASURE_FRAMES):
        screen.update(source, rotation=rotation)
        s = screen.__display.stats()
        convert += s.convert_total_us
        core1 += s.core1_rows
        frame += s.frame_us
        stall += s.stall_us

    return {"us_per_row": convert / MEASURE_FRAMES / screen.height,
            "core1_rows": core1 / MEASURE_FRAMES,
            "frame_ms": frame / MEASURE_FRAMES / 1000,
            "stall_ms": stall / MEASURE_FRAMES / 1000}


def verdict(expected, floor, ratio, core1_rows):
    """Judge one case against what its rows are allowed to do."""
    if not expected:
        if core1_rows:
            return "SPLIT SHOULD HAVE DECLINED"
        return "declines" if ratio > DECLINE_TOLERANCE else f"declined but {ratio:.2f}x"
    if not core1_rows:
        return "SPLIT NEVER ENGAGED"
    return "PASS" if ratio >= floor else f"under {floor}x"


try:
    for band_lines, cache_columns in SETTINGS:
        port = ScreenPort(SPCE_A_PINS)
        screen = SCREEN(port, band_lines=band_lines,
                        cache_columns=cache_columns, v_sync=False)
        width, height = screen.width, screen.height

        # A plain image() lands wherever the GC heap is, which on a host with PSRAM is
        # there, while canvas() places one in the SRAM region the GC never gets
        sources = {"PSRAM": image(width, height), "SRAM": screen.canvas()}
        for source in sources.values():
            draw(source)

        row_bytes = width * 3 // 2 if screen.__bitdepth == 12 else width * 2
        baudrate = screen.__display.baudrate()
        row_wire_us = row_bytes * BITS_PER_BYTE * 1_000_000 / baudrate

        print(f"{type(screen).__name__} {width}x{height} {screen.__bitdepth}-bit at "
              f"{baudrate}Hz, band_lines={band_lines} cache_columns={cache_columns}")
        print(f"  wire: {row_wire_us:.1f}us a row, {row_wire_us * height / 1000:.1f}ms "
              f"a frame, {screen.__display.sram_bytes()}B of SRAM claimed")
        print("  source rot   one core   two cores   ratio  core1 rows"
              "     one frame    two frames   verdict")

        for name in ("SRAM", "PSRAM"):
            for rotation in (0, 90):
                expected = splits(name, rotation, cache_columns)
                floor = SRAM_FLOOR if name == "SRAM" else CACHED_FLOOR
                one = measure(screen, sources[name], rotation, False)
                two = measure(screen, sources[name], rotation, True)
                ratio = one["us_per_row"] / two["us_per_row"] if two["us_per_row"] else 0
                print(f"  {name:>6} {rotation:>3}   {one['us_per_row']:>7.1f}us"
                      f"   {two['us_per_row']:>7.1f}us   {ratio:>5.2f}x"
                      f"   {two['core1_rows']:>4.0f}/{height}"
                      f"   {one['frame_ms']:>5.1f}/{one['stall_ms']:<4.1f}ms"
                      f"  {two['frame_ms']:>5.1f}/{two['stall_ms']:<4.1f}ms"
                      f"   {verdict(expected, floor, ratio, two['core1_rows'])}")
        print()

        ports.shutdown(port)
        del screen, sources, port
        gc.collect()

    print("frame columns are frame/stall. A frame at the wire figure is wire-bound, "
          "so conversion is no longer what limits it.")

finally:
    # Leave the split as it ships, whatever the run did
    spidisplay.dual_convert(True)
