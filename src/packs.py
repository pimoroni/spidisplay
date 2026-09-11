# SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# A pack is an add-on board a host takes, and each class here is the port its panel is
# on, with the pins built in and the TE line where the pack routes one. A pack
# also bringing a SP/CE connector out offers that connector's five pins as a tuple,
# which a screen port or anything else is built from.

from machine import Pin

from ports import ScreenPort, as_pins


class PicoDisplay2(ScreenPort):
    """The Pico Display Pack 2.0's panel, with TE on its own pin."""

    def __init__(self):
        super().__init__(as_pins(16, 17, 18, 19, 20), label="Display Pack 2.0", te=Pin(21))


class PicoDisplay28(ScreenPort):
    """The Pico Display Pack 2.8's panel, with TE on its own pin."""

    # The board's SP/CE output, which a chained screen or anything else is built from
    SPCE_PINS = as_pins(8, 9, 10, 11, 7)

    def __init__(self):
        super().__init__(as_pins(16, 17, 18, 19, 20), label="Display Pack 2.8", te=Pin(21))
