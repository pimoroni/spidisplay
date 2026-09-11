# SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# Checks the direct source format the firmware was built for, end to end. It covers the
# pixel size spidisplay reports, the depths it converts to, the bytes an image takes, and
# the RGB444 bytes a frame converts to, read back from the band ring as check_convert.py
# reads them.
#
# Every colour drawn has each channel a multiple of 17, so its stored nibble is exact in
# either format and both firmwares must convert it to the same packed bytes. Flat,
# axis-aligned fills keep antialiasing out of it. Run on an RGBA8888 build first and on
# the RGBA4444 build second, where the byte verdicts and the checksums have to agree.
#
# Rows are compared one at a time, so a board whose heap is its SRAM can hold the ring,
# the source and the check together. Where the GC heap owns the SRAM the display region
# is grown first, so the ring holds a whole frame.
#
# Needs a 2.8" on SP/CE A.

import gc
import time

import machine
import ports
import spidisplay
from picovector import color, image
from screens import Screen280
from ports import ScreenPort
from spce import SPCE_A_PINS

SCREEN = Screen280
STRIPES = 16
CACHE_COLUMNS = 16

# clk_sys and clk_peri per wire, as check_tearing.py sets them
CLOCKS = {
    24_000_000: (150_000_000, 48_000_000),
    37_500_000: (150_000_000, 150_000_000),
    75_000_000: (150_000_000, 150_000_000),
}

tally = {"PASS": 0, "FAIL": 0, "N/A": 0}


def verdict(kind, detail):
    tally[kind] += 1
    print(f"  {kind}  {detail}")


def stripe_rgb(index):
    # Nibble-replicated channels, so the colour survives either store exactly
    i = index % STRIPES
    return (i * 17, (15 - i) * 17, ((i * 5) % 16) * 17)


def pack444_row(colours):
    # One packed row from a list of (r, g, b), as RGB444::pack2 emits pairs
    row = bytearray()
    for x in range(0, len(colours), 2):
        r0, g0, b0 = colours[x]
        r1, g1, b1 = colours[x + 1]
        row += bytes(((r0 & 0xf0) | (g0 >> 4), (b0 & 0xf0) | (r1 >> 4), (g1 & 0xf0) | (b1 >> 4)))
    return bytes(row)


def paint_stripes(target, stripe_w):
    # Vertical stripes across the whole target, stripe_w pixels each
    for i in range((target.width + stripe_w - 1) // stripe_w):
        target.pen = color.rgb(*stripe_rgb(i))
        target.rectangle(i * stripe_w, 0, min(stripe_w, target.width - i * stripe_w), target.height)


def checksum(total, data):
    # A small order-sensitive checksum for comparing two runs by eye, fed a row at a time
    for i in range(0, len(data), 3):
        total = (total * 31 + data[i] + data[i + 1] * 7 + data[i + 2] * 13) & 0xffffffff
    return total


print("=== the compiled direct source ===")
pixel_bytes = getattr(spidisplay, "PIXEL_BYTES", None)
depths = getattr(spidisplay, "BITDEPTHS", None)
if pixel_bytes is None:
    print("  spidisplay.PIXEL_BYTES absent, an RGBA8888 build from before the setting")
    pixel_bytes = 4
    depths = (12, 16)
else:
    print(f"  spidisplay.PIXEL_BYTES = {pixel_bytes}, BITDEPTHS = {depths}")
    want = (12,) if pixel_bytes == 2 else (12, 16)
    verdict("PASS" if depths == want else "FAIL", f"depths {depths}, expected {want} at {pixel_bytes} bytes a pixel")

W, H = SCREEN.WIDTH, SCREEN.HEIGHT
ROW_BYTES = W * 3 // 2
FRAME_BYTES = ROW_BYTES * H

# A region big enough for the fastest wire's profile and for a ring holding a whole
# frame, where the GC heap owns the SRAM and the build's default block is sized for one
# panel's bands. It has to come before the first screen, and a firmware whose region is
# the free SRAM declines it.
PALETTE_BYTES = 1024        # What an indexed source's palette takes in the claim
CLAIM_SLACK = 4096          # Room for the rounding each part of the claim carries

needed = FRAME_BYTES + CACHE_COLUMNS * W * 4 + PALETTE_BYTES + CLAIM_SLACK
try:
    spidisplay.reserve(needed)
    print(f"  display region grown to {needed} bytes from the heap")
except ValueError:
    pass

print("\n=== the depth a screen resolves to ===")
try:
    for baudrate, (sys_hz, peri_hz) in CLOCKS.items():
        machine.freq(sys_hz, peri_hz)
        time.sleep(0.02)
        port = ScreenPort(SPCE_A_PINS)
        try:
            screen = SCREEN(port, baudrate=baudrate)
            chosen = screen.__bitdepth
            verdict("PASS" if chosen in depths else "FAIL",
                    f"{baudrate // 1_000_000}MHz defaults to {chosen}-bit at {screen.framerate}fps")
        finally:
            ports.shutdown(port)
finally:
    machine.freq(150_000_000, 48_000_000)
    time.sleep(0.02)

port = ScreenPort(SPCE_A_PINS)
try:
    screen = SCREEN(port, bitdepth=16)
    verdict("PASS" if 16 in depths else "FAIL", "bitdepth=16 accepted")
except ValueError as e:
    verdict("FAIL" if 16 in depths else "PASS", f"bitdepth=16 refused: {e}")
finally:
    ports.shutdown(port)

spidisplay.release_buffers()

print("\n=== converted bytes, read back from the band ring ===")
port = ScreenPort(SPCE_A_PINS)
screen = None
try:
    # Taken before the screen exists, so it spans the bands the screen claims
    region = spidisplay.buffer(spidisplay.buffer_size(), 0)
    screen = SCREEN(port, bitdepth=12, band_lines=H // 2, cache_columns=CACHE_COLUMNS)
    screen.brightness(1.0)
    base = spidisplay.buffer_size()
    ring = region[base:base + FRAME_BYTES]
    display = screen.__display
    print(f"  {W}x{H} at 12-bit, band_rows {display.band_rows()}, "
          f"claim {display.sram_bytes()} bytes at {base}")
    usable = display.sram_bytes() >= FRAME_BYTES and display.band_rows() * 2 == H
    print(f"  PREFLIGHT: {'ring holds a whole frame' if usable else 'ring cannot hold a frame, byte verdicts are N/A'}")

    def check_frame(label, source, expected, **placement):
        # expected is the packed row every output row holds, or a function of the row
        gc.collect()
        print(f"  {label}: ", end="")
        try:
            screen.update(source, offset=(0, 0), **placement)
        except (ValueError, TypeError, MemoryError) as e:
            verdict("FAIL", f"refused: {type(e).__name__}: {e}")
            return
        if not usable:
            verdict("N/A", "see preflight")
            return
        total = 0
        bad_rows = 0
        first = None
        for y in range(H):
            got = bytes(ring[y * ROW_BYTES:(y + 1) * ROW_BYTES])
            total = checksum(total, got)
            if got != (expected if isinstance(expected, bytes) else expected(y)):
                bad_rows += 1
                if first is None:
                    first = y
        if bad_rows == 0:
            verdict("PASS", f"all {H} rows match, checksum {total:08x}")
        else:
            verdict("FAIL", f"{bad_rows} rows differ, first at row {first}, checksum {total:08x}")

    def make(width, height):
        # A heap image, or None where this build's pixel size does not leave room
        gc.collect()
        try:
            return image(width, height)
        except MemoryError:
            verdict("N/A", f"no heap for a {width}x{height} image at {pixel_bytes} bytes a pixel, "
                           f"{gc.mem_free()} bytes free")
            return None

    stripe_w = W // STRIPES
    upright = pack444_row([stripe_rgb(x // stripe_w) for x in range(W)])

    print("  canvas in SRAM: ", end="")
    try:
        canvas = screen.canvas()
        got = (len(memoryview(canvas)), canvas.stride)
        want = (W * H * pixel_bytes, W * pixel_bytes)
        verdict("PASS" if got == want else "FAIL",
                f"bytes and stride {got}, expected {want} at {pixel_bytes} bytes a pixel")
        paint_stripes(canvas, stripe_w)
        check_frame("canvas in SRAM, rotation 0", canvas, upright, rotation=0)
        del canvas
    except (AttributeError, ValueError, MemoryError) as e:
        verdict("N/A", f"canvas(): {type(e).__name__}: {e}")
    gc.collect()

    heap = make(W, H)
    if heap is not None:
        paint_stripes(heap, stripe_w)
        print(f"  heap image stride {heap.stride}, {'as' if heap.stride == W * pixel_bytes else 'NOT'} {pixel_bytes} bytes a pixel")
        check_frame("heap image, rotation 0", heap, upright, rotation=0)
        del heap
        gc.collect()

    # Rotated 90 the source is H wide, and output row y takes source column y, so a
    # source of vertical stripes converts to rows of one colour each.
    side = make(H, W)
    if side is not None:
        paint_stripes(side, H // STRIPES)
        rows = [pack444_row([stripe_rgb(i)] * W) for i in range(STRIPES)]
        # Only a source in PSRAM engages the column cache, so a board without it walks the plain path
        check_frame("heap image, rotation 90", side, lambda y: rows[y // (H // STRIPES)], rotation=90)
        del side, rows
        gc.collect()

    half = make(W // 2, H // 2)
    if half is not None:
        paint_stripes(half, W // 2 // (STRIPES // 2))
        doubled_w = W // 2 // (STRIPES // 2) * 2
        doubled = pack444_row([stripe_rgb(x // doubled_w) for x in range(W)])
        check_frame("half-size heap image, pixel doubled", half, doubled,
                    rotation=0, pixel_double=True)
        del half, doubled
        gc.collect()

finally:
    ports.shutdown(port)

print(f"\n{tally['PASS']} passed, {tally['FAIL']} failed, {tally['N/A']} not applicable")
