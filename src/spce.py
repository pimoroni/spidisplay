# SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# The SP/CE connectors a host firmware names, as the pin tuples a ScreenPort or anything
# else is built from. A board names its lines SPCE_DC, SPCE_CS, SPCE_SCK, SPCE_MOSI and
# SPCE_BL in its pins.csv, with the connector's letter between where it has more than
# one, so a host is supported by adding those five names. Nothing here is board specific,
# and a connector the firmware does not name is None.

from machine import Pin

__LINE_ROLES = ("DC", "CS", "SCK", "MOSI", "BL")


def __connector(name=None):
    # The five pins named for one connector, or None where the firmware names none
    prefix = "SPCE_" if name is None else f"SPCE_{name}_"
    try:
        return tuple(getattr(Pin.board, prefix + role) for role in __LINE_ROLES)
    except AttributeError:
        return None


SPCE_PINS = __connector()       # The connector on a host that letters none
SPCE_A_PINS = __connector("A")
SPCE_B_PINS = __connector("B")
