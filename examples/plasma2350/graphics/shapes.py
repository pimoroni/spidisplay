import rp2
import time

from ports import ScreenPort, shutdown
from spce import SPCE_PINS
from screens import SCREEN_TYPES
from picovector import color, image, mat3, shape

"""
Draw every shape picovector offers, each one filled and then stroked beside it, all turning.

Reading in pairs along each row: a rectangle, a circle, an ellipse, a star, a squircle, a
pie, an arc, and a triangle as the plainest regular polygon.

Two things carry over to any drawing. A shape is built once and placed by a transform, so a
frame costs a matrix rather than a shape; and a shape is described in whatever units suit
it, unit sized here, with the scale in the transform deciding how large it lands.

Note that stroke() changes the shape it is called on rather than handing back a copy, so a
filled shape and its stroked twin are built separately below.

Press "Boot" to exit the program.
"""

# Constants for drawing
GROUND = color.rgb(10, 12, 16)          # The panel behind the shapes
ACROSS = 4                              # Cells across the panel, so two shapes to a pair
DOWN = 4                                # And down it
REACH = 0.34                            # How much of a cell's narrower side a shape takes
STROKE = 0.14                           # Stroke width, in the shape's own units
TURN_MS = 7000                          # How long a shape takes to come round
LIGHTNESS = 190                         # Every hue at one lightness, which is oklch's point
CHROMA = 110

# Which screen is on the port, "2.8" or "1.54"
SCREEN_SIZE = "2.8"
ScreenType = SCREEN_TYPES[SCREEN_SIZE]

# Create a port on the host's SP/CE connector, and the screen on it
port = ScreenPort(SPCE_PINS)
screen = ScreenType(port)

# From image(), the heap being SRAM already on a host with no PSRAM
canvas = image(screen.width, screen.height)
canvas.antialias = image.X4

CELL = canvas.width / ACROSS, canvas.height / DOWN
SIZE = min(CELL) * REACH

# Each shape at unit size around the origin, filled and then stroked. Every one is built
# here and only placed later, a shape being far dearer to make than a matrix
SHAPES = (shape.rectangle(-1, -1, 2, 2), shape.rectangle(-1, -1, 2, 2).stroke(STROKE),
          shape.circle(0, 0, 1), shape.circle(0, 0, 1).stroke(STROKE),
          shape.ellipse(0, 0, 1, 0.6), shape.ellipse(0, 0, 1, 0.6).stroke(STROKE),
          shape.star(0, 0, 5, 0.5, 1), shape.star(0, 0, 5, 0.5, 1).stroke(STROKE),
          shape.squircle(0, 0, 1), shape.squircle(0, 0, 1).stroke(STROKE),
          shape.pie(0, 0, 1, 30, 300), shape.pie(0, 0, 1, 30, 300).stroke(STROKE),
          shape.arc(0, 0, 0.6, 1, 30, 300), shape.arc(0, 0, 0.6, 1, 30, 300).stroke(STROKE),
          shape.regular_polygon(0, 0, 1, 3), shape.regular_polygon(0, 0, 1, 3).stroke(STROKE))

print(f"{len(SHAPES)} shapes in a {ACROSS}x{DOWN} grid, {SIZE:.0f}px each")

started = time.ticks_ms()

# Wrap the code in a try block, to catch any exceptions (including KeyboardInterrupt)
try:
    while not rp2.bootsel_button():
        canvas.pen = GROUND
        canvas.clear()

        turned = time.ticks_diff(time.ticks_ms(), started) / TURN_MS * 360
        for index, drawing in enumerate(SHAPES):
            # oklch asks for a hue at a lightness, so every cell reads as bright as the
            # next: hsv would hand back yellows that glare and blues that sink
            canvas.pen = color.oklch(LIGHTNESS, CHROMA, index * 360 / len(SHAPES))

            across = (index % ACROSS + 0.5) * CELL[0]
            down = (index // ACROSS + 0.5) * CELL[1]
            drawing.transform = mat3().translate(across, down).rotate(turned).scale(SIZE)
            canvas.shape(drawing)

        screen.update(canvas)

# Take the port down, and give the canvases back with it
finally:
    shutdown(port)
