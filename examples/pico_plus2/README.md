# Pico Plus 2 Screen Examples <!-- omit in toc -->

These are MicroPython examples for a [Pico Plus 2](https://shop.pimoroni.com/products/pico-plus-2), and for any host that carries PSRAM and the same SP/CE pins, the Pico LiPo 2 and Pico LiPo 2 XL W among them, whose firmware carries the `spidisplay` module and names those pins. The single-screen examples drive a display on the board's own connector. The pair examples want a [Pico Display Pack 2.8](https://shop.pimoroni.com/products/pico-display-pack-2-8) on the headers with a second display chained from the connector that pack brings out. None of them needs a file alongside it.

- [Running an Example](#running-an-example)
- [Which Ports a Pair Can Use](#which-ports-a-pair-can-use)
- [Memory on a Host With PSRAM](#memory-on-a-host-with-psram)
- [Graphics Examples](#graphics-examples)
  - [Colour Wheel](#colour-wheel)
  - [Starfield](#starfield)
  - [Shapes](#shapes)
  - [LED Matrix](#led-matrix)
- [Layout Examples](#layout-examples)
  - [Tiled Bricks](#tiled-bricks)
  - [Tiled Arrows](#tiled-arrows)
  - [Kaleidoscope](#kaleidoscope)
- [Screen Pair Examples](#screen-pair-examples)
  - [Colour Wheel In Turn](#colour-wheel-in-turn)
  - [Colour Wheel Paired](#colour-wheel-paired)
  - [Colour Wheel Facing](#colour-wheel-facing)
  - [Carpets Paired](#carpets-paired)


## Running an Example

Plug a 2.8" display into the board's SP/CE connector and run a file from `graphics/` or `layout/`. Every example draws until the Boot button is pressed, then takes its ports down: backlights out, panels asleep, buses and canvases handed back.

`SCREEN_SIZE` at the top of each file says which panel is plugged in, `"2.8"` here and `"1.54"` for the square one. A pair holds its two panels to one refresh rate, so both of them take the same size.


## Which Ports a Pair Can Use

A pair streams to both panels at once, and one SPI peripheral is one stream, so its two ports have to be on different peripherals. `ScreenPort` picks the peripheral from the clock pin, as `(sck // 8) & 1`.

On this board that rules out the arrangement you might reach for first. The host's own connector has SCK on GPIO34 and a Display Pack has it on GPIO18, and both give instance 0:

| port | SCK | peripheral |
| --- | --- | --- |
| the board's SP/CE connector | GPIO34 | SPI0 |
| a Display Pack's panel | GPIO18 | SPI0 |
| the connector a Display Pack brings out | GPIO10 | SPI1 |

So the pair examples take the pack and the connector the pack brings out, which are SPI0 and SPI1. The board's own connector is left for the single-screen examples.


## Memory on a Host With PSRAM

A Pico Plus 2 has PSRAM, and the heap lives there, so an image made with `image()` is read over the flash interface and costs about twice as much a pixel to convert. `screen.canvas()` hands back fast SRAM instead, and on this board that is worth about a third of the frame rate: the colour wheel measured 15.0fps drawing into a canvas against 11.2 into an image.

The exception is a pair drawing at full size. Both panels then convert a panel-sized image out of PSRAM inside one frame, which is what `Reserve.FULL_SIZE_IMAGES` stages for, and a pair refuses without it. That reserve takes the SRAM a full-size canvas would have used, so those examples draw into `image()` by design.

Memory is not otherwise a constraint here. `kaleidoscope.py` holds 3.6MB of frames, which no host without PSRAM can run at all.


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

An LED matrix simulated on the panel: a diagonal rainbow drawn one pixel to a lamp, scaled up, and a baked mask laid over it so each lamp reads as a round aperture. 40 by 30 lamps at full size.


## Layout Examples

### Tiled Bricks
[layout/tiled_bricks.py](layout/tiled_bricks.py)

Fill the panel with a brick wall repeated from a tile of two courses, and slide it to show the pattern has no seam.


### Tiled Arrows
[layout/tiled_arrows.py](layout/tiled_arrows.py)

Fill the panel from a wedge whose edges have nothing in common, alternating a plain repeat with a mirrored one, which turns every seam into a reflection.


### Kaleidoscope
[layout/kaleidoscope.py](layout/kaleidoscope.py)

Turn a kaleidoscope from a whole revolution of frames drawn at startup, each shown four times over by a mirrored repeat. The frames are what needs the PSRAM.


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
