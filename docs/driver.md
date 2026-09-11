# Pimoroni SP/CE Screens - Driver Reference <!-- omit in toc -->

This is the reference for `spidisplay`, the firmware module underneath the `screens` library, and it holds what a maintainer would otherwise re-derive from the code. [screens.md](screens.md) is the reference for the `screens` library, and is where a program written against a screen should start.


## Table of Content <!-- omit in toc -->
- [The Module](#the-module)
- [What a Host Firmware Needs](#what-a-host-firmware-needs)
- [Files](#files)
- [The Frame](#the-frame)
  - [The Band Ring](#the-band-ring)
  - [The SRAM Claim](#the-sram-claim)
- [The Tearing-Effect Wait](#the-tearing-effect-wait)
  - [Wiring](#wiring)
  - [The Transient Discipline](#the-transient-discipline)
  - [Reading the Line on A2 Silicon](#reading-the-line-on-a2-silicon)
  - [The Counters](#the-counters)
  - [Phase Measurement](#phase-measurement)
- [Rates](#rates)


## The Module

`spidisplay` is a panel-agnostic SPI and DMA transport. One `SPIDisplayBus` per SPI port owns the peripheral, its DMA channel and its rate. Each `SPIDisplay` on a bus owns one panel's chip select and data/command lines and streams a converted frame to it band by band, so conversion of the next band overlaps the DMA of the last.

Bringup stays in MicroPython, in `st7789.py`, which also holds the tables a panel is tuned from: the porch, the rows a refresh scans, and the rate and pixel-format codes. Nothing here knows where the pixel format came from. `bitdepth` at construction selects the packer, and `st7789.py` sends the panel the matching COLMOD.

The Python that drives the module is in `src/` and the checks that exercise it are in `tools/`, both listed in the README. Each tool builds its port from `spce` and names SP/CE A, so a host whose single connector carries no letter needs `SPCE_PINS` in place of `SPCE_A_PINS`.


## What a Host Firmware Needs

Two build settings, which a firmware built for screens carries and a stock board does not, and one arrangement of memory the driver adapts to:

- `MICROPY_PY_THREAD` at 0 when picovector is built with `PV_DUAL_CORE`. With threads on, every soft reset resets core1 under a worker that believes it is still running, and the first frame waits for it forever. Without `PV_DUAL_CORE` the driver converts on one core and threads may stay.
- `PV_PIXEL_FORMAT` set to the same value picovector is built with, before both `find_package` calls. 1 is RGBA8888, the default, and 2 is RGBA4444, which halves a canvas so a full 320x240 one fits beside the heap on a board with only SRAM. The driver reads the framebuffer at that width, and the module reports it as `spidisplay.PIXEL_BYTES`. An RGBA4444 build converts to 12-bit only, RGB565 carrying no more of a four-bit channel for a third more bytes, and `spidisplay.BITDEPTHS` lists what a build accepts.
- Where the displays' region comes from. With PSRAM fitted and `MICROPY_GC_SPLIT_HEAP` at 0, the whole GC heap lives in PSRAM and the linker's SRAM heap range is free: the region is that range, costing the heap nothing. Otherwise the GC owns the SRAM, on a board with no PSRAM or under the rp2 port's default of a split heap whenever PSRAM is fitted, and the region is a block taken from the heap. `SPIDISPLAY_HEAP_RESERVE_BYTES` in the consumer's cmake sizes that block, 40KB by default, one panel with margin, and `spidisplay.reserve(bytes)` before the first screen resizes it for two panels or for canvases. A split heap can only hand out SRAM while its first area has room, so a block landing in PSRAM is refused with the setting named. On a host with no PSRAM every heap address is SRAM, so an ordinary picovector image is already the fast source and the region need only hold the displays.

The stepping needs nothing from the board: the driver reads it and handles erratum E9 itself, as [Reading the Line on A2 Silicon](#reading-the-line-on-a2-silicon) describes. Verified on a Pico Plus 2 with A2 silicon on 2026-09-07, both breakout revisions, tear-free at 45Hz.


## Files

`driver/` is the half that references no MicroPython API, which is why `tests/` can build it on a host. `bindings/` is the half that does.

| file | holds |
| --- | --- |
| `driver/spidisplay.hpp`, `driver/spidisplay.cpp` | the bus, the display and the frame state machine, knowing nothing of MicroPython bar the C-linkage calls reaching this file's own state |
| `bindings/spidisplay_bindings.cpp` | the two types wrapping those classes, and `update_all()` and `te_phase()`, which take several displays at once |
| `bindings/spidisplay_bindings.c`, `bindings/spidisplay_bindings.h` | the module table, `buffer()`, `buffer_size()`, `release_buffers()` and `dual_convert()`, and the declarations the three binding files share |
| `driver/scanline.hpp` | the conversion kernels: RGBA8888 or RGBA4444 (whichever picovector was built for) or palettised source to RGB444 or RGB565 rows, with rotation, mirror, pixel doubling and tiling |
| `driver/descriptor.hpp` | the descriptor a kernel walks, built once per frame from the source, the placement and the rotation |
| `driver/pixel_formats.hpp` | the source traits and one packer per destination format, each owning its format's arithmetic. `PV_PIXEL_FORMAT` picks the direct source |
| `driver/column_cache.hpp` | a cache of source columns for rotated frames, so a rotation-90 row does not read one pixel per PSRAM line |
| `driver/interleaver.hpp` | `update_all()`, driving several displays on different buses through a frame at once |
| `driver/sram_allocator.hpp` | the region of fast SRAM the GC heap does not use, claimed from the top by displays and from the bottom by canvases |


## The Frame

`update()` composes four resumable steps, which `update_all()` drives for several displays at once:

1. `prepare()` builds the conversion descriptor, seeds the column cache and converts as far ahead as the band ring allows. It sets the bus rate and DMA word width, sends nothing and never waits on the bus.
2. `arm()` begins the tearing-effect wait without blocking: the TE line goes to input, the stale level is recorded and the timeout starts. `poll_te()` samples the rising-then-falling wait and returns true once the frame may start, by edge or by timeout. `step()` may convert ahead meanwhile.
3. `start_stream()` sends RAMWR and kicks the first band, timestamped as `write_start_us`.
4. `step()` converts at most a slice of rows into the back band, kicks it when full and the channel is free, and raises CS once everything has drained.

Only displays on different buses interleave. Displays sharing a bus are driven as a broadcast group instead, one display carrying every member's CS and DC bits.

### The Band Ring

The band buffers form a ring of `ceil(stage_lines / band_lines)` slots, at least two. A height that `band_lines` does not divide ends in a shorter final band, sized where it is converted and kicked. Conversion may run the whole ring ahead of the wire, which is what lets a slow source convert during the TE wait and hold a head start against the wire's pace.

One slot always stays reserved for the transfer in flight, whether or not the channel reports busy. Reclaiming it on the live busy flag lets a whole-band conversion slip in at the moment a transfer completes, ahead of the waiting kick, and the wire starves for that conversion. Measured on the 2.8" at 24MHz, a row converts in 32.5 to 38.1us from SRAM and 72.9 to 86.9us from PSRAM, against a 142.5us wire row, so a band of a dozen rows is half a millisecond of starvation at best and over a millisecond from PSRAM.

Kicks are interrupt driven, from the DMA_IRQ_2 handler. `kick_from_isr()` runs in ISR context, is limited to the channels the owner table names and touches no state, stats or MicroPython. It kicks the next converted band or timestamps the wire starving.

`stall_us` in `FrameStats` is therefore the wire genuinely starving for conversion: near zero means the frame was wire-bound, and growth means the conversion could not keep the ring fed. `stall_row` is where that first happened, the row the wire was waiting for, and -1 for a frame that never starved. The drain at the end of every frame counts toward `stall_us` but never sets `stall_row`.

`stall_row` is always a band boundary, so a starving band and a panel tearing at a fixed row look alike until it is read. A tear with `stall_row` at -1 is not a starvation, and the panel's scan direction not following MADCTL, noted under [Rates](#rates) below, is the likelier cause.

### The SRAM Claim

The region is the SRAM between the linker's GC heap symbols where a firmware put its whole GC heap in PSRAM, and a block taken from the heap where the GC owns that SRAM instead. [What a Host Firmware Needs](#what-a-host-firmware-needs) above says which a host gets and how the block is sized. The bindings choose, reading where the port's first heap area landed, and the driver's allocator is bound to whichever it is handed. A heap block lives in root pointers, so a soft reset drops it with the rest of the heap and the next screen takes a fresh one.

Each display claims its band ring, its column cache storage and the palette an indexed source is drawn through as one block from the top of the SRAM region, at construction. The palette is per display because interleaving drives several through frames concurrently, and in SRAM because a per-pixel indirection into PSRAM would reintroduce the XIP miss the column cache exists to remove. A broadcast copy shares its first member's claim and releases nothing, so the wrapper roots the member for the group's lifetime.

`buffer()` claims canvases from the bottom of the same region. The views have no owner to finalise them, so `release_buffers()` belongs with releasing the screens that drew to them.

The module functions over that region, none of which belongs to either type:

| call | does |
| --- | --- |
| `buffer(nbytes)` | claims from the bottom and returns a writable `memoryview`, for a picovector image that converts at half the cost of one in PSRAM |
| `buffer(nbytes, offset)` | places a view by hand at an offset from the region's base, bounded by the display workspaces but claimed from nothing, so it may overlap another view |
| `buffer_size()` | the bytes a claim can still take, which shrinks with screens and canvases and recovers on release |
| `release_buffers()` | drops every canvas claim at once. A view still held then points at space the next claim can take |
| `dual_convert()` | whether a frame's rows are halved across both cores, on by default. `dual_convert(enable)` sets it, and turning it off leaves one core, for timing the two against each other |
| `PIXEL_BYTES` | bytes per pixel of the direct source this build reads, 4 for RGBA8888 and 2 for RGBA4444, so a canvas can be sized without naming either |
| `BITDEPTHS` | the panel depths this build converts to, `(12, 16)` for RGBA8888 and `(12,)` for RGBA4444 |


## The Tearing-Effect Wait

`te < 0` at construction reads the signal from the DC line, which is how a host with one panel and no pin to spare wires it: the DC line is flipped to an input for the wait. Otherwise `te` is a dedicated input GPIO, as an add-on board's panel has.

### Wiring

`cs` must be unique per panel, being the only signal selecting one. `dc` may be shared, but not by panels using TE without a diode: each breakout ties TE to that line through a series resistor, so panels sharing it divide the line and the asserted level is lost.

Behind a multiplexer a DC line carrying TE needs an analog mux to pass both directions. A demux or buffer fails quietly, the wait timing out and `te_timeouts()` counting it, while the frame still streams.

### The Transient Discipline

A shared line may carry one panel's signal at a time. A non-zero `sync_cs` on `prepare()` names the member whose TE the frame waits on, and the display sends that member TEON as the wait begins and TEOFF as the frame goes idle. The sync and target masks belong to the frame and clear with it, so no TEON outlives the frame that asked for it and no narrowed write leaves a mask behind for the next one.

### Reading the Line on A2 Silicon

RP2350 steppings before A4 carry erratum E9: a pad with its pull-down enabled latches near 2.2V once the line has been high, so a released TE line would read high for good after its first pulse and every wait would run to its timeout.

The driver reads the stepping once, from the bootrom version since CHIP_ID's revision field is the same on A3 and A4, and on those parts drives the line low for a microsecond and releases it before every read. A panel holding TE high recharges the line through its resistor or diode inside the settle, and a low stays low. Measured on an A2 Pico Plus 2, the frame time is unchanged.

### The Counters

Three cumulative counts say how the waits went, none of which is part of the frame snapshot:

- `te_timeouts()`: frames that began without their TE edge. A frame still goes out, so this is the only sign `v_sync` did not hold.
- `te_short_waits()`: frames whose wait ended on a pulse it watched rise and that fell inside `SHORT_WAIT_US`, 700us, which is above TE mode 2's 500us H-sync pulses and below the shortest measured blanking, 1,277us on the 1.54" and 1,536us on the 2.8". A pulse train defeats it: TE mode 2 rises within 17us of the release, inside `JOINED_HIGH_US`, so those waits book as joined and `te_probe()`'s period is what names that fault. It has no known live case on the panels this driver ships with, and is kept for the hosts and panels it has not met.
- `te_joined_waits()`: frames whose wait began with the line already high, so the pulse it ended on started unobserved. One a frame means a line released from a high and decaying through the pull-down. The occasional one is a held frame arming inside a blanking, which reaches a real fall late and is no fault.

`JOINED_HIGH_US` is 50us: over the 14us an arm and its two settled samples cost, far under the thousands an arm during the active scan waits for a blanking.

### Phase Measurement

`te_phase()` captures falling edges on two displays' lines from one loop and folds them onto a period, so a pair's skew is measured without writing a frame. It copes with the roughly 47us TESCAN-narrowed pulse, which a Python capture cannot.

`te_capture()` keeps one line's raw edges instead, which is what a shared DC line needs: a hub is swept member by member and each fall aged by that panel's period onto a common instant.

Neither may run while a frame is staged or streaming, a staged frame owning the DC line TE is read from.


## Rates

`baudrate` is per panel and asserted against the bus before every transfer, so mixed panel types can share a port. The divider only reaches `clk_peri / (2 * n)`, so a request is rounded down, sometimes a long way. `baudrate()` reports what was reached, and the Python wrapper refuses a request the clock cannot meet.

`sync_delay_us` on `update()` starts the stream that long after the TE wait releases, which places a broadcast write inside every member's tearing margin instead of at the synced member's own top edge. `write_start_us` moves with it.

`compatible_with()` requires the same bus and agreement on everything the stream depends on. Register state bringup put in the panel is not compared, MADCTL included, which is not licence to vary it: the scan direction does not follow MADCTL, so a flipped panel tears.
