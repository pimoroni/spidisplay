import rp2
from packs import PicoDisplay28
from ports import ScreenPort, shutdown
from screens import SCREEN_TYPES, ScreenPair
from picovector import image, color, shape, mat3

"""
Spin a rainbow wheel on a pair of screens held in step. Change up some of the constants
below to see what happens.

Press "Boot" to exit the program.
"""

# Constants for drawing
INNER_RADIUS = 40
OUTER_RADIUS = 120
NUMBER_OF_LINES = 24
HUE_SHIFT = 4
ROTATION_SPEED = 2
LINE_THICKNESS = 2

# Which screen is on both ports, "2.8" or "1.54".
# A pair aligns its panels, which needs their rates close, and the two sizes default
# too far apart to bridge, so both panels take one size here
SCREEN_SIZE = "2.8"
ScreenType = SCREEN_TYPES[SCREEN_SIZE]

# The Display Pack is a port already, and a second screen chains from the SP/CE connector
# it brings out, so the two panels are on separate buses as a pair needs
panel = PicoDisplay28()
chained = ScreenPort(PicoDisplay28.SPCE_PINS, label="the pack's SP/CE out")

# A pair holds its two panels to one refresh rate and keeps their scans together, so a
# frame reaches both without a tear band walking across either. Working out how takes a
# few seconds when the pair is created, and it goes on correcting as the program runs.
#
# The default reserve keeps both panels fed here, the canvas being in SRAM on a host with
# no PSRAM. Reserve.FULL_SIZE_IMAGES is for a pair converting a panel-sized image out of
# PSRAM, which costs about twice as much a pixel. color_wheel_in_turn.py draws the same
# wheel without a pair, for comparison
pair = ScreenPair(ScreenType(panel), ScreenType(chained))

# Access the first screen and create a canvas to draw to. A pair's panels are the same
# size as each other, so either one gives the size to draw at
first = pair.screens[0]
canvas = image(first.width, first.height)

# Pre-calculate the screen centre
centre_x, centre_y = first.width / 2, first.height / 2


# Variables to keep track of rotation and hue positions
r = 0
t = 0

# Create a line shape to use throughout the program
line = shape.line(INNER_RADIUS, 0,  # Start position (x, y)
                  0, OUTER_RADIUS,  # End position (x, y)
                  LINE_THICKNESS)

# Wrap the code in a try block, to catch any exceptions (including KeyboardInterrupt)
try:
    while not rp2.bootsel_button():
        # Clear the canvas to black
        canvas.pen = color.black
        canvas.clear()

        # Go from 0 to 360 degrees, in equal divisions for the number of lines
        for i in range(0, 360, 360 // NUMBER_OF_LINES):
            # Calculate the colour hue of the line, giving full saturation and value
            hue = (i * 255) // 360
            canvas.pen = color.hsv((hue + t) % 256, 255, 255)

            # Rotate the line we originally create, and move it towards the screen centre
            line.transform = mat3().translate(centre_x, centre_y).rotate(i + r)

            # Apply the line with the current pen colour to the canvas
            canvas.shape(line)

        # Update the pair with the latest canvas, which draws it to both panels
        pair.update(canvas)

        # Advance both the rotation and the hue
        r += ROTATION_SPEED
        t += HUE_SHIFT

# Take both ports down, and give the canvases back with them
finally:
    shutdown(panel, chained)
