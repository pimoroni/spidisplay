import rp2

from ports import ScreenPort, shutdown
from spce import SPCE_PINS
# from packs import PicoDisplay28
from picovector import color, shape
from screens import SCREEN_TYPES

"""
Fill the whole panel with a brick wall drawn from a tile of 32 by 32 pixels.

That tile is 4KB where a wall covering the panel would be a full-size image of 307KB, so tiling
is the difference between an asset that fits anywhere and one that has to be budgeted for.

A running bond is what makes the tile so small: one course is a brick and its mortar, and the
course above is the same moved sideways by half a brick, so two courses is everything the pattern
ever does. The brick starting halfway along the upper course finishes on the far side of the tile,
so it is drawn twice, once at each end. That is the whole trick to a source that tiles, a shape
crossing an edge having to appear at the opposite edge as well.

Press "Boot" to exit the program.
"""

# Constants
ROTATION = 90            # Quarter turn, to suit how the screen is mounted
BRICK_W = 32             # A brick and its mortar, which is the tile's width
BRICK_H = 16             # A course, two of which is the tile's height
MORTAR = 3               # How wide the gaps between bricks are
STEP = 1                 # Pixels the wall slides each frame, to show it has no seam
FACE = color.rgb(168, 68, 52)
FACE_TOP = color.rgb(196, 96, 76)     # The weathered top edge of a brick
FACE_FOOT = color.rgb(132, 48, 38)    # And its shaded foot
GROUT = color.rgb(196, 188, 172)

# Which screen is on the port, "2.8" or "1.54"
SCREEN_SIZE = "2.8"
ScreenType = SCREEN_TYPES[SCREEN_SIZE]

# Create a port on the host's SP/CE connector, and the screen on it
port = ScreenPort(SPCE_PINS)
# port = PicoDisplay28()   # A Display Pack on the headers, in place of the connector
screen = ScreenType(port)

# Two courses of one brick, and the driver makes a wall of it
wall = screen.canvas(BRICK_W, BRICK_H * 2)
print(f"a {BRICK_W}x{BRICK_H * 2} wall tile, {BRICK_W * BRICK_H * 2 * 4 // 1024}KB,"
      f" filling {screen.height}x{screen.width}")


def brick(x, y):
    """One brick at (x, y), its face laid over the mortar with a lit top and dark foot."""
    width, height = BRICK_W - MORTAR, BRICK_H - MORTAR
    wall.pen = FACE_TOP
    wall.shape(shape.rectangle(x, y, width, height))
    wall.pen = FACE
    wall.shape(shape.rectangle(x, y + 1, width, height - 2))
    wall.pen = FACE_FOOT
    wall.shape(shape.rectangle(x, y + height - 1, width, 1))


# Mortar first, since every brick is laid over it and the gaps are what is left showing
wall.pen = GROUT
wall.clear()

# The lower course starts at the edge, the upper one half a brick along. Drawing that one
# twice, half a brick to either side of the tile, is what carries it across the seam
brick(0, 0)
brick(BRICK_W // 2, BRICK_H)
brick(BRICK_W // 2 - BRICK_W, BRICK_H)

frames = 0

# Wrap the code in a try block, to catch any exceptions (including KeyboardInterrupt)
try:
    while not rp2.bootsel_button():
        # Sliding the wall proves there is no seam in it: the courses run on for ever in
        # both directions, from those three bricks
        screen.update(wall, rotation=ROTATION,
                      offset=(-frames * STEP, -frames * STEP), tile=True)
        frames += 1

# Take the port down, and give the canvases back with it
finally:
    shutdown(port)
