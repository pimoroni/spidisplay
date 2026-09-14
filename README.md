# SP/CE Display Library <!-- omit in toc -->

## Colour LCD displays for SP/CE hosts, driven from MicroPython <!-- omit in toc -->

This repository is home to the `screens` MicroPython library for the Pimoroni SP/CE displays, and to `spidisplay`, the firmware module underneath it that converts each frame and sends it to the panel.

[![Build Status](https://img.shields.io/github/actions/workflow/status/pimoroni/spidisplay/tests.yml?branch=main&label=Tests)](https://github.com/pimoroni/spidisplay/actions/workflows/tests.yml)

- [Introduction](#introduction)
- [Supported Hardware](#supported-hardware)
- [Getting Started](#getting-started)
- [How It Works](#how-it-works)
- [What You Can Do](#what-you-can-do)
- [Documentation](#documentation)
- [What's In This Repository](#whats-in-this-repository)
- [Building a Firmware With the Module](#building-a-firmware-with-the-module)
- [Running the Tests](#running-the-tests)


## Introduction

A SP/CE display is a colour LCD panel on a breakout board, joined to a host board's SP/CE port by one ribbon cable. The cable carries the panel's power, its data lines and its backlight, so a display is one plug and no soldering.

Two sizes are supported: a 1.54" square panel at 240x240 pixels, and a 2.8" panel at 240x320. An add-on board carries one of these panels and seats on a host's headers instead of taking a cable, and the same library drives it.

You draw with [picovector](https://github.com/pimoroni/picovector), and the library sends the result to the panel:

```python
screen.update(canvas)
```

Behind that one call, the library converts your image and streams it to the panel in step with the panel's own refresh, so what you see never tears. It can hold several displays together too, which means a pair of panels or a whole wall of them change as one.


## Supported Hardware

Two add-on boards carry a panel of the same kind, and each is a class in `packs` with its pins built in:

* Pico Display Pack 2.0 - https://shop.pimoroni.com/products/pico-display-pack-2-0
* Pico Display Pack 2.8 - https://shop.pimoroni.com/products/pico-display-pack-2-8

The 2.8" also brings a SP/CE connector out, which a second display chains from.

A host is an RP2350 board whose firmware is built with the `spidisplay` module and names its SP/CE pins, a Pico Plus 2 among them, and a host with more than one connector drives a display on each.


## Getting Started

Our boards often come pre-flashed with MicroPython and the libraries needed to get you started, and you program them with an interpreter such as [Thonny](https://thonny.org/). If you are new to working with Pico, this Learn Guide goes into more detail:

* [Getting Started with Pico](https://learn.pimoroni.com/article/getting-started-with-pico)

A screen needs the port it is plugged into and the size of the panel. On an add-on board the port is the class in `packs`, its pins already known:

```python
from packs import PicoDisplay28
from screens import Screen280
from picovector import color

screen = Screen280(PicoDisplay28())

canvas = screen.canvas()
canvas.pen = color.blue
canvas.clear()
screen.update(canvas)
```

The panel comes up cleared and its backlight stays dark until you have drawn your first frame, so nothing flashes up on whatever the panel was left showing.

On a host with a SP/CE connector, such as a Pico Plus 2, `spce` carries that connector's pins and a `ScreenPort` is built from them:

```python
from ports import ScreenPort
from spce import SPCE_PINS

port = ScreenPort(SPCE_PINS)
```

[examples/](examples/) has programs to run on a host as they are, and [docs/screens.md](docs/screens.md) takes it from here, with the full library reference.


## How It Works

A panel wants its pixels in its own format, and the SPI bus to it wants them one after another, so a frame is two jobs: converting it and sending it. `spidisplay`, the firmware module this repository is named for, does both at once. It converts a band of rows at a time and hands each finished band to the SPI peripheral over DMA while it converts the next, so the bus is never waiting on the conversion.

Rotation, mirroring, pixel doubling and tiling happen inside that conversion, as strides on a pointer the loop is walking anyway, so they need no second pass over the image.

That overlap is what buys the frame rates, and the panel decides the rest. A panel refreshes on a clock of its own, and a frame that outruns one refresh tears, so every rate the library ships was measured on a real panel and set a step below where tearing began.


## What You Can Do

* **Draw without tearing.** Every frame waits for the panel's refresh, so a loop that draws and updates runs at the panel's own frame rate and the picture stays whole.
* **Place an image any way round.** Rotate, mirror, centre, offset or tile a source over the panel, and draw a half-size image doubled to fill it at a quarter of the memory.
* **Drive two screens as one.** A `ScreenPair` streams a frame to both panels at once and holds their refreshes together, so a pair takes about the time a single screen would.
* **Drive a whole wall.** Several screens on one port, such as those on a hub, can be written as a single `ScreenGroup`, with the members still addressable one at a time.
* **Dim the backlight evenly.** Brightness runs from 0.0 to 1.0 against perceived brightness, so equal steps look equal.


## Documentation

* [docs/screens.md](docs/screens.md) - the library reference: connecting a screen, drawing to it, placing an image, pairs, groups and hubs.
* [docs/playback.md](docs/playback.md) - the playback reference: animated GIFs and folders of images, and the clock they run on.
* [docs/driver.md](docs/driver.md) - the driver reference, for anyone building the `spidisplay` module into a firmware or working on it.


## What's In This Repository

| directory | holds |
| --- | --- |
| `src/` | the MicroPython side: the `screens` package, `ports.py` for the lines a panel is driven over, `st7789.py` for the panel controller, `packs.py` and `spce.py` for where those lines come from, `playback.py` for animations a screen is given, and `logging.py` |
| `driver/` | the C++ driver, which references no MicroPython API and so builds on a host |
| `bindings/` | the MicroPython bindings around that driver |
| `examples/` | MicroPython examples per host, for a screen on its SP/CE connector or on an add-on board, one panel or two |
| `tools/` | on-board checks: bringing up a new panel or a new host, measuring the frame rate a panel holds at a given bus speed, and confirming the converter and the players put out what they should |
| `tests/` | host tests that compile the driver headers and drive them from Python |
| `docs/` | the screens, playback and driver references |


## Building a Firmware With the Module

Put this directory on the module path and ask cmake for it:

```cmake
find_package(SPIDISPLAY CONFIG REQUIRED)
```

The module reads the picovector pixel format and needs a couple of build settings to agree with it. [docs/driver.md](docs/driver.md) says which, and what memory the driver expects to find.


## Running the Tests

The host tests compile the driver behind a C-linkage wrapper and drive it with ctypes, so they need no board:

```
python3 -m pip install pytest
python3 -m pytest tests -v
```

They run on both g++ and clang++ in CI, since the two schedule the conversion kernels differently and the tests assert exact bytes.
