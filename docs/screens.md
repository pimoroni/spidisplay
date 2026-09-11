# Pimoroni SP/CE Screens - Library Reference <!-- omit in toc -->

This is the library reference for the SP/CE displays, as driven from any Pimoroni SP/CE host through the `screens` module.


## Table of Content <!-- omit in toc -->
- [Getting Started](#getting-started)
- [Connecting a Screen](#connecting-a-screen)
- [Drawing to a Screen](#drawing-to-a-screen)
- [Placing an Image](#placing-an-image)
- [Driving Two Screens Together](#driving-two-screens-together)
  - [Alignment](#alignment)
- [Driving Several Screens as One](#driving-several-screens-as-one)
  - [Waiting on One Member](#waiting-on-one-member)
  - [Alignment](#alignment-1)
- [Using a Hub](#using-a-hub)
- [Choosing a Profile](#choosing-a-profile)
- [Reserving Fast Memory](#reserving-fast-memory)
- [The Controller Module](#the-controller-module)
- [`ScreenPort` Reference](#screenport-reference)
  - [Variables](#variables)
  - [Properties](#properties)
  - [Functions](#functions)
- [`Backlight` Reference](#backlight-reference)
  - [Functions](#functions-1)
- [`Screen` Reference](#screen-reference)
  - [Constants](#constants)
  - [Properties](#properties-1)
  - [Functions](#functions-2)
- [`Screen154` and `Screen280` Reference](#screen154-and-screen280-reference)
- [`Reserve` Reference](#reserve-reference)
- [`Tile` Reference](#tile-reference)
- [`ScreenPair` Reference](#screenpair-reference)
  - [Properties](#properties-2)
  - [Functions](#functions-3)
- [`ScreenGroup` Reference](#screengroup-reference)
  - [Properties](#properties-3)
  - [Functions](#functions-4)
- [`ScreenHub` Reference](#screenhub-reference)
  - [Constants](#constants-1)
  - [Properties](#properties-4)
  - [Functions](#functions-5)
- [Diagnostics](#diagnostics)


## Getting Started

A screen is driven over a `ScreenPort`, built from the five lines the panel needs in the order DC, CS, SCK, MOSI, BL. Nothing names the SPI instance, which the clock pin's GPIO number decides.

On a host with a SP/CE connector, `spce` carries that connector's pins as a tuple, read from the names the firmware gives them:

```python
from ports import ScreenPort
from spce import SPCE_PINS

port = ScreenPort(SPCE_PINS)
```

A host with more than one connector letters them, as `SPCE_A_PINS` and `SPCE_B_PINS`. A connector the firmware does not name is `None`, and building a port on it says so.

An add-on board is a class in `packs`, already a port for its own panel, with its pins and its TE line built in. Only the 2.8" brings a SP/CE connector out, as `PicoDisplay28.SPCE_PINS`, which a further screen chains from:

```python
from packs import PicoDisplay28
from ports import ScreenPort

panel_port = PicoDisplay28()
out_port = ScreenPort(PicoDisplay28.SPCE_PINS)
```

Each of these is a plain tuple of pins, so a program putting a connector to some other use reads its lines from the same constant.

`ScreenPort` accepts GPIO numbers as well as `Pin` objects, and a string naming a pin the firmware knows, such as `"SPCE_DC"`. `as_pins(16, 17, 18, 19, 20)` in `ports` turns numbers into objects. A board with a library of its own hands finished ports out instead, and a screen is built on one of those the same way.

Whichever way the port was made, create a screen of the size that is plugged in and draw to it:

```python
from screens import SCREEN_TYPES
from picovector import image, color

screen = SCREEN_TYPES["2.8"](port)

canvas = image(screen.width, screen.height)
canvas.pen = color.white
canvas.clear()
screen.update(canvas)
```

`SCREEN_TYPES` maps a size, `"1.54"` or `"2.8"`, to its class, `Screen154` or `Screen280`. Either class can be used directly. A screen type carries its panel's settings, so a new size is a subclass of `Screen` setting a few attributes, and a one-off is a keyword override at construction.

The first screen on a port takes the port's own chip select, data/command and backlight lines and needs no pins named. The panel comes up cleared and its backlight stays dark until the first frame has been drawn, so nothing lights up on whatever the panel held at power-on.


## Connecting a Screen

Every further screen on the same port names its `cs`, and its `dc` unless it is deliberately sharing the port's. A screen built against one of a `ScreenHub`'s ports names none of them, the hub having named the whole line-up already.

`te` names the line the panel's tearing-effect signal comes back on. The signal marks the start of each refresh, and waiting on it is what keeps a frame from tearing:

- `True`, the default on a connector, is this screen's own data/command line, which is how a connector wires a single panel to a port.
- The port's own data/command line, `port.dc`, is a line other screens share. This needs a diode on each breakout, and the signal is only asserted for the frame waiting on it.
- Any other `Pin` is a dedicated input.
- `False` turns the signal off and never waits. Use it for a panel wired without its tearing-effect signal, which is then not looked for.
- `None` takes the port's default: `True` on a connector, the shared line on a hub.

Where `te` is in play, construction raises `ValueError` if no panel answers on that line, which is how an empty port or an unplugged panel reports itself. A refusing screen claims nothing, so a program may build a line-up and keep whichever screens were found.

`v_sync` follows `te`, and `v_sync=False` keeps the signal without waiting on it. Each `update()` can name its own `v_sync`.

`bl=False` declines the port's backlight, for a panel whose own is tied on at the assembly.

`rotation` and `mirror` say how the panel is mounted, and every frame follows them unless it sets its own. `rotation` is 0, 90, 180 or 270 degrees clockwise.

`reveal_together=True` holds the port's backlight until every screen asking for it has drawn, so a line-up comes up as one. A panel never drawn holds the line dark, so only ask on the screens the program covers. `brightness()` still lights it.


## Drawing to a Screen

`update()` streams an image to the panel. Any picovector image will do, but on a host with PSRAM the main heap lives there, so an image made with `image()` is read over the flash interface and costs about twice as much per pixel to convert. `canvas()` hands back an image in fast SRAM instead, by default sized to the screen:

```python
canvas = screen.canvas()
canvas.pen = color.blue
canvas.clear()
screen.update(canvas)
```

Each size is claimed once from the screen's own share of the SRAM and handed back on every later call, so two screens never share pixels. Half the panel's width and height, drawn with `pixel_double=True`, is a quarter of the bytes: two screens can hold one each where one full-size canvas already fills the region. `canvas(offset=...)` places a canvas by hand at a byte offset into the region, outside the claims.

On a host with no PSRAM, such as a Pico 2 or a Plasma 2350 W, the heap is SRAM already, so an image made with `image()` is the fast source and the budget is the heap itself: a full-size 2.8" image is 307KB, more than the heap has left once the firmware and the screens are in. Draw to a half-size image and pass `pixel_double=True`, or to a smaller image that `update()` centres on `bg_color`. A palettised source is one byte a pixel, a quarter of the size again. A firmware built with picovector at RGBA4444 halves every image instead, so a full-size canvas fits: `canvas()` sizes itself from `spidisplay.PIXEL_BYTES` either way.

`update()` blocks until the frame has left. With `v_sync` on it first waits for the panel's refresh to start, so a loop that draws and updates runs at the panel's frame rate and nothing tears. A frame's own `v_sync` overrides the screen's for that call.

The backlight stays dark until the first frame has been drawn. Calling `brightness()` before that ends the wait and lights the panel on the bare fill bringup left it with, so draw first. `brightness()` sets how bright it looks, from 0.0 to 1.0 against perceived brightness, so equal steps look equal. 0.0 is off and every setting above it is one the panel shows. `backlight` carries the rest of the control, `on()` and `off()` among it, and is `None` for a screen built with `bl=False`.


## Placing an Image

The image need not match the panel. Every frame is placed by the same settings, and each defaults to the screen's own or to a per-call default:

- `rotation` and `mirror` follow the screen's construction unless the frame sets them, so a program says how the panel is mounted once and the loop says only what changes.
- `pixel_double=True` draws each source pixel as a 2 by 2 block, so a half-size image fills the panel at a quarter of the memory and conversion cost.
- `offset=None` centres the image on both axes. An `(x, y)` pair places its top-left corner, and either element may be `None` to centre just that axis. The offset is in panel pixels, after rotation.
- `tile` repeats the source along its own axes, one value for both or an `(x, y)` pair. Each value is `False`, `True` or `Tile.MIRROR`, the last reversing every other repeat so each seam is a reflection: any source tiles seamlessly, and half an image mirrored fills the whole panel.
- `bg_color` fills whatever the image does not cover, black by default.

`prepare()` takes the same placement settings and stages a frame without sending it, for `update_pair()` below. Nothing reaches the panel until the pair is updated.


## Driving Two Screens Together

Two screens on their own SP/CE ports can be presented together as one. A `ScreenPair` streams a frame to both panels at once, so a pair takes about the time one screen alone would, and holds their refreshes together so the two change as one:

```python
from screens import ScreenPair, Screen280
from ports import ScreenPort
from spce import SPCE_A_PINS, SPCE_B_PINS

pair = ScreenPair(Screen280(ScreenPort(SPCE_A_PINS)),   # A pair needs a connector each
                  Screen280(ScreenPort(SPCE_B_PINS)))
pair.update(canvas)
```

One image reaches both panels, or a second positional image gives each its own: `pair.update(left, right)`. Every placement setting takes one value for both screens, or a pair of values for one each, so two panels mounted opposite ways is `rotation=(90, 270)`. Unnamed, `rotation` and `mirror` follow each screen's own construction. `offset` and `tile` are already `(x, y)` pairs, so they are shared unless an element is itself a pair:

```python
offset=(5, 10)              # both screens at (5, 10)
offset=(5, None)            # both screens: x=5, y centred
offset=(None, (5, 10))      # first centred, second at (5, 10)
offset=((0, 0), (5, 10))    # one each
tile=(True, False)          # both screens tile x only
tile=((True, True), False)  # first tiles both axes, second neither
tile=(Tile.MIRROR, False)   # both screens tile x, every other repeat reflected
```

Both screens must be on different ports, since one port is one stream, and must agree on `reserve`, since a reservation is shared out across the pair. [Reserving Fast Memory](#reserving-fast-memory) below says what that setting claims. They need not be the same size: a pair drives a 1.54" and a 2.8" together, where a group is built over matching screens only. `reveal_together=True` on the pair asks it of both screens, so the two backlights come up on one refresh.

### Alignment

Two panels refresh from their own oscillators, so left alone their refreshes drift apart and one panel shows a new frame tens of milliseconds before the other. With `align` on, the pair measures both panels' refresh periods, brings the faster panel's onto the slower's, and then corrects the small remaining drift on every frame. After a pause long enough for the pair to drift apart, the next `update()` spends one frame catching up while the stale content hides it, so resuming costs one late frame.

`align=None`, the default, aligns where the pair can. Construction calibrates for about four seconds, saying so on the console. A pair too mismatched to hold alignment says why and runs unaligned, and `is_aligned()` then reports `False`. `align=True` raises `ValueError` for such a pair instead, and `align=False` leaves the panels alone. `start_aligning()` takes the four seconds later, and `stop_aligning()` stops.

Alignment needs both screens built with `te` and `v_sync`, and an aligned pair refuses `v_sync=False` on a frame, the signal being what it measures by. Alignment adjusts the following panel's refresh; updating that screen on its own, outside the pair, hands its own refresh back, as does `stop_aligning()`.

`update_pair(first, second)` is the plain entry underneath: it streams whatever frames the two screens have `prepare()`d, with no alignment.


## Driving Several Screens as One

Several screens on one port, such as those on a hub, can be driven as one `ScreenGroup`. One stream reaches every member, so a wall of panels shows a frame in the time one of them takes:

```python
from screens import ScreenGroup

wall = ScreenGroup(*screens)
wall.update(canvas)
```

The members keep their identity, so each can still be updated on its own. A group is built over screens agreeing on size, bit depth, rate and tuning, and takes its size, bit depth, backlight and `reserve` from its first member. A screen belongs to one group at a time.

`rotation` and `mirror` are the group's own, since one stream is one placement, and default to upright. The members' own placement is not used by a group write, and the group says so on the console where the two differ. A member updated on its own still places by its own.

A group of one member is allowed, so a program written for a hub still runs where a single panel answered.

`subset(*screens)` names fewer of the members over the same stream, for a frame that reaches only some of them, and `update(image, to=(...))` does the same for one frame. A subset owns nothing, so bind one and reuse it; where the membership changes each frame, `to=` takes a tuple and costs less than building a subset every time.

`reveal_together=True` asks it of every member. One group write covers them all, so it only matters where a subset covers part of the line-up.

### Waiting on One Member

Panels on a hub refresh independently, so there is no moment when a frame is safe for all of them. `leader` names the one member whose tearing-effect signal a frame waits on: that panel comes out clean and the rest may tear. This needs every member built with `te` set to the shared data/command line, as a hub does by default. `None`, the default, takes the first member that can, saying so on the console if none can. `False` declines the wait, so a frame goes out at once.

### Alignment

With `align` on, the group brings its members' refreshes into step and holds them there, so a frame lands untorn on all of them. Construction calibrates each member for a fraction of a second, saying so on the console, matches each panel's refresh to the slowest, and brings their refreshes together. From then on every frame the group writes also nudges any member that has drifted, a scan line at a time.

`align=None`, the default, aligns where the group can and otherwise says why and runs held to one member's signal only. `align=True` raises `ValueError` where the members cannot be held. `align=False` leaves the panels alone. `is_aligned()` reports the state reached, so it reads `False` where a request went unmet or a long pause lost the members.

A frame after a long pause first waits for the members to come back together, up to about half a second, then goes out and tears on any still out of step, since a stalled wall is worse than one spoiled frame.

`trim` says how the group keeps its members' rates current as the panels warm. `None`, the default, rotates the member each frame waits on so every panel is measured in turn, among the panels that frame writes, so a subset written on its own takes turns among its own members. `"probe"` re-measures one member every thirty frames instead, stalling that frame briefly. `False` turns it off. Only a group that aligned has anything to trim.


## Using a Hub

A hub carries several screens on one SP/CE port, each addressed by a chip select of its own. Build the `ScreenHub` before any screen on that port, naming the extra chip selects in the order the hub letters them, then build each screen against one of the hub's ports as it would be built against the connector:

```python
from screens import ScreenHub, Screen280
from ports import ScreenPort
from spce import SPCE_A_PINS, SPCE_B_PINS

hub = ScreenHub(ScreenPort(SPCE_A_PINS), extra_cs=SPCE_B_PINS)   # Spare host GPIOs, or a second connector's five lines
screens = [Screen280(port) for port in hub.ports]
```

`ports[0]` is the connector's own chip select and the rest follow `extra_cs` in the order given. The ports are lettered as well: `hub.a` is `ports[0]`, `hub.b` the next, matching the lettering on the hub itself. The letters run `a` to `z`, so any port past the twenty-sixth is reached through `ports`.

`te` names the line the tearing-effect signal comes back on, and defaults to the shared data/command line. That declares a diode on every breakout, which stops each panel's own signal from pulling the shared line down. Without diodes the panels divide the line and no signal survives, so a build without them passes `te=False`. The firmware cannot see a diode, so the declaration is yours.

Every panel the hub reaches is reset and cleared as the hub is built, whether a screen is created for it afterwards or not. A panel holds its last frame across a soft reset, so one the program leaves out would otherwise light up showing the previous run.

A screen built against a hub port that has no panel raises `ValueError` and claims nothing, so a program can build a screen on every port and keep the ones that answered.


## Choosing a Profile

Each screen type carries a table of measured tuning, `PROFILES`, keyed by SPI baud rate and bit depth. Naming only a `baudrate` lands on the settings that profiling chose for that wire:

```python
screen = Screen280(port, baudrate=37_500_000)
```

Settings resolve as: an explicit keyword, then the `PROFILES` row for the (`baudrate`, `bitdepth`) pair, then the class constants. With no `bitdepth` named, the first depth in `DEPTHS` that has a row for the baud rate wins, so the faster wires default to 16-bit colour and `bitdepth=12` buys their last few frames per second. A firmware built with picovector at RGBA4444 converts to 12-bit only, `spidisplay.BITDEPTHS` saying so, and the default follows. Every resolved value is checked against the controller's tables, so a bad experiment fails where the mistake is.

The rates run below 60fps because a frame shares the panel with its own refresh. A frame that takes longer than the refresh leaves it to tear, so each profile's rate is the fastest the panel's scan can hold while the wire keeps ahead of it, stepped down where a panel's oscillator spread would otherwise leave no margin.

A row's `"dual"` entry, where it has one, replaces the row on a firmware that converts frames on both cores, since some wires reach a higher rate once one core is no longer what the wire waits for. The firmware decides by default. `dual_profiles=True` or `False` chooses the set by hand, for measuring one against the other, and is a diagnostic setting.

A baud rate the current peripheral clock cannot reach is refused, since the divider would round the wire down and run the profile's tuning slower than it was measured on. Raise the clock first, `machine.freq(150_000_000, 150_000_000)`, or request a rate the clock reaches.

`band_lines`, `cache_columns` and `stage_lines` override what the profile chose, for profiling a new panel or wire. The first two spend fast SRAM from the same region canvases come from, at least two band buffers plus `cache_columns * width * spidisplay.PIXEL_BYTES` bytes, for as long as the screen lives. `band_lines` need not divide the height; the last band of a frame is shorter. `stage_lines` deepens the band buffers into a ring of that many rows, which `prepare()` converts ahead of the frame.

A `PROFILES` row is measured, not derived. `tools/profile_screens.py` sweeps a wire's settings on the panel and records each cell's frame time, and `tools/check_tearing.py` shows a chosen rate holding, drawing the worst case, a heap image at rotation 90, and printing the margin the refresh leaves. A rate that shows no torn band there is one to keep, and `tools/check_te_margin.py` reports the margin of a single setting.


## Reserving Fast Memory

`reserve` says what the screen's share of the fast SRAM is for, and is the setting to reach for ahead of the three above:

- `Reserve.CANVAS_SPACE`, the default, claims only what a frame needs and leaves the region for `canvas()`.
- `Reserve.FULL_SIZE_IMAGES` claims enough for two screens to each convert a full-size image out of PSRAM at once, through `update_pair()`. That is the one case that cannot keep up otherwise. A full-size canvas no longer fits alongside it; half-size ones still do.

The reserve buys a frame that does not tear, not a faster one: the conversion moves into `prepare()`, ahead of the frame, so the wire never starves but the pair takes longer to come round. Drawing to `canvas()`, or halving an image and passing `pixel_double=True`, needs neither.

Both screens of a pair need the same reserve, which `update_pair()` checks. The reservation is shared out across the pair, so one on its own leaves both short.

`Reserve.FULL_SIZE_IMAGES` is only available where a screen type has a measured recipe for the wire, in its `FULL_IMAGE_RESERVE`, and raises `ValueError` elsewhere. Both shipped sizes carry one at 24MHz 12-bit.


## The Controller Module

`st7789` is the module `Screen.CONTROLLER` names, and everything specific to the panel's controller lives there: the register opcodes, the bringup sequence `setup()` writes, and the tables a screen's settings are checked against. `FRAME_RATE_CONTROL` maps a frame rate to its code, and its keys are the only rates a screen accepts. `PIXEL_FORMAT` maps a bit depth, 12 or 16, to its code, which is the one place the panel is told its pixel format; the driver underneath packs to the depth the screen was built with. `PORCH` is the back and front porch `setup()` writes, in scan lines, and `set_porch()` changes them, which is how alignment moves a panel's refresh. `CONTROLLER_ROWS`, 320, is the rows a refresh scans whatever the panel's height, so a 240-row panel scans 80 it does not show, and `LINE_SLOTS` is that plus both porches: a refresh period divided by it is the panel's line time. `TE_ON`, `TE_OFF` and `TE_MODE` are the opcodes the frame path uses to switch one panel's tearing-effect signal onto a shared line.

`setup()` leaves the panel unflipped, since the controller's scan direction does not follow its `MADCTL` register and a panel flipped there tears. Rotation and mirroring are done in the frame path instead.

A second controller is a new module of the same shape, named through `CONTROLLER` on a `Screen` subclass.


## `ScreenPort` Reference

The five lines one or more screens are driven over, and the bus they share. `label` names the port in its refusals, and is the one setting a caller may write to afterwards. The shutting-down calls are separate so a program can take a port down in stages, and `shutdown()` does all three in order. `release()` is the one to reach for where a program builds screens repeatedly, since nothing else hands a bus's DMA channel back and the SDK panics once the sixteen are gone.

### Variables
```python
label: str                  # The name this port gives itself in a refusal
```

### Properties
```python
dc: Pin
cs: Pin
sck: Pin
mosi: Pin
bl: Pin
```

### Functions
```python
# Initialisation
ScreenPort(pins: tuple[int | Pin | str],
           label: str=None,
           te: int | Pin=None)

# Shutting down
backlight_off() -> None
stop_panels() -> None
release() -> None
shutdown() -> None

# Module functions
as_pins(*numbers: int) -> tuple[Pin]
gpio_number(pin: Pin) -> int
shutdown(*ports: ScreenPort) -> None
```

`shutdown(*ports)` takes every port down and gives the canvases back, which is what a board's own shutdown does. A port's own `shutdown()` leaves them, another port's screens may still be drawing to them, so `spidisplay.release_buffers()` is what returns them once every port is down.


## `Backlight` Reference

A port's backlight, shared by every screen on it and reached as `screen.backlight`. Dark from power-on until a screen on the port has shown a frame, so no panel lights on whatever bringup left it holding.

### Functions
```python
brightness(value: float) -> None
on() -> None
off() -> None
toggle() -> None
```

`brightness()` sets the level and lights to it, which also ends any wait for a frame. `off()` keeps the level for the next `on()`, and `toggle()` inverts the setting.


## `Screen` Reference

### Constants
```python
CONTROLLER = st7789        # The module supplying the bringup sequence and code tables
PROBE_MS = 60              # A present panel always answers inside this
PATIENT_PROBE_MS = 250     # The second look an empty line pays

WIDTH = HEIGHT = None      # Set by each screen type
BITDEPTH = 16
FRAMERATE = 60
BAUDRATE = 24_000_000
BAND_LINES = 12            # With CACHE_COLUMNS, the tuning for a wire PROFILES does not cover
CACHE_COLUMNS = 12
DEPTHS = (16, 12)          # Bit depth preference when none is named, first row wins

FULL_IMAGE_RESERVE = {}    # Reserve.FULL_SIZE_IMAGES recipes, per (baudrate, bitdepth)
PROFILES = {}              # Measured tuning, per (baudrate, bitdepth)
```


### Properties
```python
port: ScreenPort
backlight: Backlight | None
screens: tuple[Screen]
width: int
height: int
rotation: int
mirror: bool
reveal_together: bool
framerate: int              # The refresh rate the screen was built with
requested_baudrate: int     # The rate asked for, which the SPI clock divider may have rounded down
```


### Functions
```python
# Initialisation
Screen(port: ScreenPort,
       cs: int=None,
       dc: int=None,
       te: bool | int=None,
       v_sync: bool=None,
       bl: bool=True,
       width: int=None,
       height: int=None,
       bitdepth: int=None,
       framerate: int=None,
       baudrate: int=None,
       reserve: int=Reserve.CANVAS_SPACE,
       band_lines: int=None,
       cache_columns: int=None,
       stage_lines: int=None,
       dual_profiles: bool=None,
       rotation: int=0,
       mirror: bool=False,
       reveal_together: bool=False)

# Drawing
canvas(width: int=None, height: int=None, offset: int=None) -> Image
update(image: Image, *, rotation: int=None, mirror: bool=None, pixel_double: bool=False,
       offset: tuple[int, int]=None, tile: bool | int=False, bg_color: Color=None,
       v_sync: bool=None, to: tuple[Screen]=None) -> None
prepare(image: Image, *, rotation: int=None, mirror: bool=None, pixel_double: bool=False,
        offset: tuple[int, int]=None, tile: bool | int=False, bg_color: Color=None,
        to: tuple[Screen]=None) -> None

# Backlight
brightness(value: float) -> None
```


## `Screen154` and `Screen280` Reference

`Screen154` is the 1.54" screen, 240 by 240 pixels. `Screen280` is the 2.8" screen, 240 by 320. Each carries four `PROFILES` rows, and a `FULL_IMAGE_RESERVE` recipe at 24MHz 12-bit.

| profile | `Screen154` | `Screen280` |
| --- | --- | --- |
| 24MHz, 12-bit | 53fps | 45fps |
| 37.5MHz, 16-bit | 60fps | 52fps |
| 37.5MHz, 12-bit | 60fps | 55fps, 60fps on a two-core firmware |
| 75MHz, 16-bit | 60fps | 53fps, 60fps on a two-core firmware |

Neither carries a 16-bit row at 24MHz, where the wire is too slow to finish a frame inside the controller's slowest refresh, or a 12-bit row at 75MHz, where it is fast enough that the write overtakes the panel's scan and tears near the top.

```python
SIZE: str                   # The key in SCREEN_TYPES, "1.54" or "2.8"; a new type picks the string its size is known by
WIDTH: int
HEIGHT: int
```


## `Reserve` Reference

```python
CANVAS_SPACE = 0            # Only what a frame needs, leaving the region for canvas()
FULL_SIZE_IMAGES = 1        # Room to convert a full-size heap image while a paired screen does the same
```


## `Tile` Reference

```python
OFF = 0                     # What False means
REPEAT = 1                  # What True means
MIRROR = 2                  # Every other repeat reversed, so each seam is a reflection
```


## `ScreenPair` Reference

### Properties
```python
screens: tuple[Screen, Screen]
```

### Functions
```python
# Initialisation
ScreenPair(first: Screen, second: Screen, align: bool=None, reveal_together: bool=False)

# Drawing
update(image: Image, second: Image=None, *, rotation=None, mirror=None, pixel_double=False,
       offset=None, tile=False, bg_color=None, v_sync: bool=None) -> None

# Alignment
is_aligned() -> bool
start_aligning() -> None
stop_aligning() -> None

# Module function
update_pair(first: Screen, second: Screen, v_sync: bool=None) -> None
```


## `ScreenGroup` Reference

A group is a `ScreenBase`, so it carries the `Screen` variables and functions above, `canvas()`, `update()` and `prepare()` among them.

### Properties
```python
screens: tuple[Screen]      # The members
```

### Functions
```python
# Initialisation
ScreenGroup(*screens: Screen,
            leader: Screen | bool=None,
            align: bool=None,
            trim: bool | str=None,
            rotation: int=None,
            mirror: bool=None,
            reveal_together: bool=False)

# Members
subset(*screens: Screen, leader: Screen | bool=None, reveal_together: bool=False) -> ScreenGroup

# Alignment
is_aligned() -> bool
```


## `ScreenHub` Reference

### Constants
```python
BLIND_BAUDRATE = 24_000_000    # What the bringup pass runs at, before any screen sets its own
BLIND_BITDEPTH = 12
BLIND_FRAMERATE = 60
BLIND_BAND_LINES = 2
```

### Properties
```python
ports: tuple[ScreenHubPort]    # One per chip select, in the order named
a, b, c, ...: ScreenHubPort    # The same ports by letter, a to z
```

### Functions
```python
ScreenHub(port: ScreenPort,
          extra_cs: tuple[int | Pin]=(),
          dc: Pin=None,
          te: bool | Pin=None,
          controller=st7789)
```


## Diagnostics

The screens report on the console through the `logging` module. At the default level, `LOG_INFO`, they say when a calibration starts and finishes, and why an alignment request went unmet. `logging.level = logging.LOG_DEBUG` adds the figures behind those notices: a pair's porch padding and the drift left after it, a group's verified periods and their spread, every trim correction with the member it moved, the walk engaging and finishing, how many periods a frame was held for the members to come together, and any capture whose falls did not span a plausible period. One panel of a group tearing shows up there first, as the member the corrections keep naming.

Per-frame timing and the tearing-effect counters belong to the driver underneath the screens, not to this API. The tools in `tools/` read them, `check_tearing.py` printing a profile's margin and `check_te_margin.py` a single setting's, and [driver.md](driver.md) documents what they measure.
