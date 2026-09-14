# Plasma 2350 Screen Examples <!-- omit in toc -->

These are MicroPython examples for a SP/CE display on a [Plasma 2350](https://shop.pimoroni.com/products/plasma-2350) or [Plasma 2350 W](https://shop.pimoroni.com/products/plasma-2350-w), whose firmware carries the `spidisplay` module and names the connector's pins. Each one draws with picovector alone, so none of them needs a file alongside it.

- [Running an Example](#running-an-example)
- [Memory on a Host Without PSRAM](#memory-on-a-host-without-psram)
- [Graphics Examples](#graphics-examples)
  - [Colour Wheel](#colour-wheel)
  - [Starfield](#starfield)
  - [Shapes](#shapes)
  - [LED Matrix](#led-matrix)
- [Layout Examples](#layout-examples)
  - [Tiled Bricks](#tiled-bricks)
  - [Tiled Arrows](#tiled-arrows)


## Running an Example

Plug a 2.8" display into the SP/CE connector and run the file. Each one builds its port from `spce.SPCE_PINS` and its screen from `SCREEN_SIZE` at the top, which is `"2.8"` here and `"1.54"` for the square panel.

Every example draws until the Boot button is pressed, and then takes the port down: the backlight goes out, the panel sleeps, and the bus and canvases are handed back.


## Memory on a Host Without PSRAM

A Plasma 2350 has no PSRAM, so the heap is SRAM already and every source here is an ordinary `image()`. `screen.canvas()` is for a host whose heap is PSRAM, where it hands back fast SRAM instead; on this board the driver's region is itself a block of the same heap, so a canvas is no faster than an image and only has to be reserved for in advance.

What a panel-sized image costs depends on the pixel format the firmware's picovector was built at, which `spidisplay.PIXEL_BYTES` reports: at two bytes a pixel a 2.8" image is 150KB, and at four it will not fit beside the rest of a program. A frame that will not fit is drawn at half size and passed with `pixel_double=True`, which is a quarter of the memory and of the conversion.


## Graphics Examples

### Colour Wheel
[graphics/color_wheel.py](graphics/color_wheel.py)

Spin a wheel of rainbow spokes, drawn from one line shape placed by a matrix.


### Starfield
[graphics/starfield.py](graphics/starfield.py)

Travel through a field of stars, each growing as it falls away from the centre.


### Shapes
[graphics/shapes.py](graphics/shapes.py)

Every shape picovector offers, filled and then stroked beside it, all turning in a grid.


### LED Matrix
[graphics/led_matrix.py](graphics/led_matrix.py)

An LED matrix simulated on the panel: a diagonal rainbow drawn one pixel to a lamp, scaled up, and a baked mask laid over it so each lamp reads as a round aperture. Drawn at half the panel's size and doubled on the way out, the matrix and its mask being two images.


## Layout Examples

### Tiled Bricks
[layout/tiled_bricks.py](layout/tiled_bricks.py)

Fill the panel with a brick wall repeated from a tile of two courses, and slide it to show the pattern has no seam.


### Tiled Arrows
[layout/tiled_arrows.py](layout/tiled_arrows.py)

Fill the panel from a wedge whose edges have nothing in common, alternating a plain repeat with a mirrored one, which turns every seam into a reflection.
