# Pico 2 Screen Examples <!-- omit in toc -->

These are MicroPython examples for a [Pico 2](https://shop.pimoroni.com/products/raspberry-pi-pico-2), or a [Pico 2 W](https://shop.pimoroni.com/products/raspberry-pi-pico-2-w), carrying a [Pico Display Pack 2.8](https://shop.pimoroni.com/products/pico-display-pack-2-8), whose firmware carries the `spidisplay` module. The pack's own panel is one screen and its SP/CE connector chains a second, so the examples come in three sets: one screen, one screen with the frame placed some way, and two screens driven together. None of them needs a file alongside it.

- [Running an Example](#running-an-example)
- [The Two Ports](#the-two-ports)
- [Memory on a Host Without PSRAM](#memory-on-a-host-without-psram)
- [Graphics Examples](#graphics-examples)
  - [Colour Wheel](#colour-wheel)
  - [Starfield](#starfield)
  - [Shapes](#shapes)
  - [LED Matrix](#led-matrix)
- [Layout Examples](#layout-examples)
  - [Tiled Bricks](#tiled-bricks)
  - [Tiled Arrows](#tiled-arrows)
- [Screen Pair Examples](#screen-pair-examples)
  - [Colour Wheel In Turn](#colour-wheel-in-turn)
  - [Colour Wheel Paired](#colour-wheel-paired)
  - [Colour Wheel Facing](#colour-wheel-facing)
  - [Carpets Paired](#carpets-paired)

Anything here runs on another Pico-form RP2350 host with the same pack, the pins coming from the pack rather than from the board.


## Running an Example

Seat the pack on the host and run the file. The pair examples want a 2.8" display on the pack's SP/CE connector as well, and every example draws until the Boot button is pressed, then takes its ports down: backlights out, panels asleep, buses and canvases handed back.

`SCREEN_SIZE` at the top of each file says which panel is plugged in, `"2.8"` here and `"1.54"` for the square one. A pair holds its two panels to one refresh rate, so both of them take the same size.


## The Two Ports

The pack is a port already, its pins built in, and the screen on it is the pack's own panel:

```python
from packs import PicoDisplay28

panel = PicoDisplay28()
```

The connector the pack brings out is a second port, built from the pins the pack publishes:

```python
from ports import ScreenPort

chained = ScreenPort(PicoDisplay28.SPCE_PINS)
```

The two land on different SPI peripherals, which is what lets a `ScreenPair` stream to both at once. A Pico 2 has no SP/CE connector of its own, so `spce.SPCE_PINS` is `None` here and building a port on it says so.


## Memory on a Host Without PSRAM

A Pico 2 has no PSRAM, so the heap is SRAM already and every source here is an ordinary `image()`. `screen.canvas()` is for a host whose heap is PSRAM, where it hands back fast SRAM instead; on this board the driver's region is itself a block of the same heap, so a canvas is no faster than an image and only has to be reserved for in advance.

A pair needs no deeper reserve for the same reason. `Reserve.FULL_SIZE_IMAGES` buys a staging ring for two panels converting panel-sized images out of PSRAM, which costs about twice as much a pixel; reading from SRAM keeps both panels fed at the default.

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


## Screen Pair Examples

### Colour Wheel In Turn
[pair/color_wheel_in_turn.py](pair/color_wheel_in_turn.py)

The colour wheel on two screens held separately, each updated after the other, which is what a pair is measured against.


### Colour Wheel Paired
[pair/color_wheel_paired.py](pair/color_wheel_paired.py)

The same wheel through a `ScreenPair`, which streams one frame to both panels and holds their refreshes together, so the two change as one.


### Colour Wheel Facing
[pair/color_wheel_facing.py](pair/color_wheel_facing.py)

The paired wheel with the second panel mirrored, for two screens mounted facing each other.


### Carpets Paired
[pair/carpets_paired.py](pair/carpets_paired.py)

A different carpet tiled over each panel, each drifting its own way, from one call that carries an image and an offset per screen.
