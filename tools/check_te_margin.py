# SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# Measures each panel's real refresh period from its TE line and reports the tear
# margin left over a measured frame. Oscillators vary per unit, so two panels at one
# setting can hold different margins, and a small or negative one shows as a
# marginal tear wobbling in and out on that panel alone.

import spidisplay
import st7789
from picovector import color, image
from screens import Screen280
from ports import ScreenPort
from spce import SPCE_A_PINS, SPCE_B_PINS

PROBE_MS = 1000

port_a = ScreenPort(SPCE_A_PINS)
port_b = ScreenPort(SPCE_B_PINS)
# v_sync off leaves frame_us the pipeline alone, while te stays on for the probe below
screens = (Screen280(port_a, v_sync=False),
           Screen280(port_b, v_sync=False))
labels = ("SP/CE A", "SP/CE B")

WIDTH, HEIGHT = screens[0].width, screens[0].height
canvas = image(HEIGHT, WIDTH, spidisplay.buffer(HEIGHT * WIDTH * spidisplay.PIXEL_BYTES))
# The buffer holds whatever the region last carried, so the frame is given a colour
canvas.pen = color.rgb(127, 127, 127)
canvas.clear()

nominal = screens[0].framerate
print("FRCTRL2 steps:", sorted(st7789.FRAME_RATE_CONTROL))
print("nominal rate: {}fps, nominal two-refresh budget: {}us".format(
    nominal, 2_000_000 // nominal))
print()

for label, screen in zip(labels, screens):
    display = screen.__display
    screen.update(canvas, rotation=90)   # Warm, so the timed frame pays no setup
    screen.update(canvas, rotation=90)
    frame_us = display.stats().frame_us

    probe = display.te_probe(PROBE_MS)
    period_us, high_us, edges = probe
    if edges < 2:
        print("{}: TE silent ({} edges)".format(label, edges))
        continue

    actual_fps = 1_000_000 / period_us
    budget_us = 2 * period_us     # Two refreshes, this panel showing every scanned line
    margin_us = budget_us - frame_us
    print("{}: TE period {}us ({:.2f}fps actual), high {}us, {} edges".format(
        label, period_us, actual_fps, high_us, edges))
    print("   frame {}us against budget {}us: margin {}us ({:.1f}% of budget)".format(
        frame_us, budget_us, margin_us, 100 * margin_us / budget_us))
    print()
