# SPDX-FileCopyrightText: 2026 Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# A pack is an add-on board a host takes, and each class here is the port its soldered
# panel is on, with the pins built in and the TE line where the pack routes one. A pack
# also bringing an SP/CE connector out offers it as spce().

from spce import SPCE, SPCEPort


class PicoDisplay2(SPCEPort):
    """The Pico Display Pack 2.0's soldered panel, on SPI0 with TE on its own pin."""

    def __init__(self):
        super().__init__("PANEL", SPCE.SCREEN, 0, (16, 17, 18, 19, 20), te=21)


class PicoDisplay28(SPCEPort):
    """The Pico Display Pack 2.8's soldered panel, on SPI0 with TE on its own pin.

    spce() is the SP/CE output on the other bus, which a chained screen is built on.
    """

    def __init__(self):
        super().__init__("PANEL", SPCE.SCREEN, 0, (16, 17, 18, 19, 20), te=21)

    @staticmethod
    def spce(mode=SPCE.SCREEN):
        """The board's SP/CE output, on SPI1."""
        return SPCEPort("A", mode, 1, (8, 9, 10, 11, 7))
