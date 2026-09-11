# SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
#
# SPDX-License-Identifier: MIT
#
# A port a screen is driven over, holding the five lines a panel needs and the SPI bus
# and backlight the screens on it share. An add-on board builds its own from its pin
# table and a host builds one from the pins its firmware names. The double-underscore
# methods are the contract a screen is built through, forwarded to here by a hub's
# ports, and each line is checked before a screen is built and claimed once it is, so a
# refusal partway leaves nothing behind.

import logging
import time

from machine import PWM, Pin
from spidisplay import SPIDisplayBus, release_buffers


def as_pins(*numbers):
    """The given GPIO numbers as Pin objects, a pin tuple reading better as numbers."""
    return tuple(Pin(number) for number in numbers)


def gpio_number(pin):
    """The GPIO number behind a Pin."""
    # A Pin gives up its number only through its repr, Pin(GPIO34, ...)
    return int(str(pin)[8:].split(",")[0])


class Backlight:
    """A screen backlight, a PWM line driven the way a board drives its LEDs.

    Dark from power-on until a screen on its port has shown a frame, so no panel lights
    on what bringup left it holding, and reveal_together holds it until every screen
    asking has drawn. 0.0 is off and every setting above it lands somewhere the panel
    answers, so the range a caller is given is the range they can see. Screens on one
    port share the line and so the setting.
    """

    # Duty follows the setting raised to this, since perceived brightness goes as
    # roughly the cube root of light output. Chosen on the panel against 2.2 and 3.0.
    GAMMA = 2.8

    # Where a setting above zero starts, measured on holding a steady level rather than
    # on lighting at all, which fails later. The worst of six 2.8" units was unsteady at
    # 17.7us and the worst of four 1.54" at 13.3us. One figure whatever the panel, a
    # port's one BL line serving every screen on it.
    MINIMUM_PULSE_US = 20

    # The PWM rate, audible and kept so, leaving the band costing most of the range,
    # since the same pulse is 40% duty at 20kHz. A clk_sys change after this moves it.
    FREQUENCY = 1000
    MINIMUM_DUTY = MINIMUM_PULSE_US * FREQUENCY / 1_000_000

    def __init__(self, port, pin):
        self.__pwm = PWM(Pin(pin), freq=self.FREQUENCY, duty_u16=0)
        self.__port = port
        self.__level = 1.0     # What a frame lights to, and what on() restores
        self.__control = 0.0   # The setting as it was asked for, which toggle inverts
        self.__lit = False
        self.__waiting = True  # Dark until a frame lands, against dark by choice
        self.__shown = []      # The screens asking to reveal together that have drawn
        self.__said = False    # Whether the wait has already explained itself

        # The minimum in the terms the gamma reads, so a setting maps onto it there
        self.__lowest = pow(self.MINIMUM_DUTY, 1.0 / self.GAMMA)

    def brightness(self, value):
        """Set the level and light to it, which also ends any wait for a frame.

        0.0 is off and keeps the level for the next on(), so a caller can use either
        spelling. Everything above it spans MINIMUM_DUTY to full.
        """
        value = min(1.0, max(0.0, value))
        if self.__waiting:
            self.__waiting = False
            self.__shown = []   # Nothing left to count, so the screens are let go

        self.__control = value
        self.__lit = value > 0.0
        if self.__lit:
            self.__level = value

        # Folded into the curve the gamma reads and not into the duty, since that curve
        # is what steps evenly to the eye. Offsetting the duty instead would spend the
        # first quarter of the range going nowhere anyone could see.
        if self.__lit:
            self.__duty(self.__lowest + value * (1.0 - self.__lowest))
        else:
            self.__duty(0.0)

    def __duty(self, curve):
        # Drive the line at a point on the gamma curve, 0.0 to 1.0
        self.__pwm.duty_u16(int(pow(curve, self.GAMMA) * 65535 + 0.5))

    def off(self):
        """Take the line dark, keeping the level for on()."""
        self.brightness(0.0)

    def toggle(self):
        """Invert the setting, as a board's LEDs do.

        Its own, not the curve the duty follows, which carries the minimum folded in.
        """
        self.brightness(1.0 - self.__control)

    def on(self):
        """Light the line at the level it last held."""
        if not self.__lit:
            self.__wait_a_scan()

        self.brightness(self.__level)

    def __frame_shown(self, source=None, to=None, keep_dark=False):
        # Note a frame reaching the glass, which is what a dark line waits for. Only from
        # power-on, a line taken dark by off() staying dark until asked for again. source
        # is what was written and to the panels it reached, and with neither the first
        # frame lights the line whatever any screen asked for. keep_dark leaves the line
        # unlit and hands back the scan to spend before __reveal_now(), None saying the
        # line is not ready and nothing is owed.
        if not self.__waiting:
            return None

        if source is not None:
            asked = False
            fresh = False
            for screen in (source.screens if to is None else to):
                if screen.reveal_together:
                    asked = True
                    if screen not in self.__shown:
                        self.__shown.append(screen)
                        fresh = True

            waiting_for = self.__waiting_for()
            if waiting_for:
                # Said once, and only where a frame covered panels already counted, which
                # is a loop not reaching the rest and the one shape a caller cannot see
                if asked and not fresh and not self.__said:
                    self.__said = True
                    logging.info(f"screens: the backlight is waiting for {waiting_for} more "
                                 f"screen{'' if waiting_for == 1 else 's'} to show a frame "
                                 f"before it lights. Update {'it' if waiting_for == 1 else 'them'}, "
                                 f"call backlight.on() to light it now, or create the screens "
                                 f"without reveal_together.")
                return None

        if keep_dark:
            return self.__scan_ms

        self.__wait_a_scan()
        self.brightness(self.__level)
        return None

    def __forget_screens(self):
        # Let go of the screens counted so far, their port having released them. The wait
        # itself stays where it is, re-arming it would blink a line already up
        self.__shown = []

    def __waiting_for(self):
        # How many screens asking to reveal together have yet to show a frame
        return sum(1 for screen in self.__port.__screens
                   if screen.backlight is self and screen.reveal_together
                   and screen not in self.__shown)

    @property
    def __scan_ms(self):
        # One full scan of the slowest screen on the port, in milliseconds. A finished
        # transfer is not a presented frame, each row keeping what the scan last painted
        # there until the scan passes again
        slowest = self.__port.__slowest_framerate
        return 0 if slowest is None else 1000 // slowest + 3

    def __reveal_now(self):
        # Light at the held level, for a caller that has already spent the scan
        self.brightness(self.__level)

    def __wait_a_scan(self):
        # Hold for one full scan before the light comes up
        time.sleep_ms(self.__scan_ms)


class ScreenPort:
    """The five lines one or more screens are driven over, and the bus they share.

    Built from the pins in the order DC, CS, SCK, MOSI, BL, whether those come from a
    connector, an add-on board or a caller's own wiring. The SPI
    instance follows from the clock pin, so nothing names it.
    """

    # The lines in the order they are given, which is what a refusal names
    LINE_NAMES = ("dc", "cs", "sck", "mosi", "bl")

    def __init__(self, pins, label=None, te=None):
        """Construct a port over five pins, given as GPIO numbers or Pin objects.

        label names this port in its refusals. te is the line a panel's tearing-effect
        signal comes back on, and defaults to the screen's own data/command line.
        """
        if pins is None:
            raise ValueError("A screen port needs five pins, in the order DC, CS, SCK, "
                             "MOSI, BL. None usually means a firmware that names no such "
                             "connector, so check the board's pins.csv.")

        if len(pins) != len(self.LINE_NAMES):
            raise ValueError(f"A screen port needs five pins, in the order DC, CS, SCK, "
                             f"MOSI, BL. {len(pins)} were given.")

        # Pin() hands back the same object where it is given one, so a number or a Pin
        # both land here, and so does a string naming a pin the firmware knows
        self.__pins = tuple(Pin(pin) for pin in pins)
        self.label = label if label else "Screen port"

        self.__spi = self.__spi_instance()

        # The contract a screen reads by attribute, uniform with a hub's port. A lone
        # panel reads TE from its own DC line, unless the port names the pin TE comes to.
        self.__connector = self
        self.__dc_line = self.__pins[0]
        self.__default_te = True if te is None else Pin(te)

        self.__spi_bus = self.__make_bus()
        self.__backlight = None
        self.__screens = []
        self.__cs_claimed = []
        self.__dc_claimed = []
        self.__panels_reset = False

    def __spi_instance(self):
        # Which SPI peripheral these pins reach, from the clock line. RP2 SCK pins
        # alternate between SPI0 and SPI1 every eight GPIOs, SCK sitting two past a
        # multiple of four and the data line one past that.
        sck, mosi = (gpio_number(pin) for pin in self.__pins[2:4])
        if sck % 4 != 2 or mosi % 4 != 3:
            raise ValueError(f"{self.label} has SCK on GPIO {sck} and MOSI on GPIO {mosi}, "
                             "which no SPI peripheral reaches. SCK is two past a multiple "
                             "of four and MOSI the pin after it.")

        instance = (sck // 8) & 1
        if instance != ((mosi // 8) & 1):
            raise ValueError(f"{self.label} has SCK on GPIO {sck} and MOSI on GPIO {mosi}, "
                             "which are on different SPI peripherals. Both lines have to "
                             "reach the same one.")

        return instance

    # Pass dc or cs to a screen to share that line
    @property
    def dc(self):
        """The port's data and command line, which the first screen on it takes."""
        return self.__pins[0]

    @property
    def cs(self):
        """The port's chip select, which the first screen on it takes."""
        return self.__pins[1]

    @property
    def sck(self):
        """The port's SPI clock, which its bus is made on."""
        return self.__pins[2]

    @property
    def mosi(self):
        """The port's SPI data line, which its bus is made on."""
        return self.__pins[3]

    @property
    def bl(self):
        """The port's backlight line, which every screen on it shares."""
        return self.__pins[4]

    def __make_bus(self):
        return SPIDisplayBus(spi=self.__spi, sck=self.__pins[2], mosi=self.__pins[3])

    @property
    def __bus(self):
        # The SPIDisplayBus every screen on this port streams over. Made again where
        # release() gave its DMA channel back, so a port built on a second time takes a
        # fresh channel instead of handing out a dead bus
        if self.__spi_bus is None:
            self.__spi_bus = self.__make_bus()

        return self.__spi_bus

    @property
    def __slowest_framerate(self):
        # The lowest panel refresh rate on the port, which sets any wait for a frame to
        # reach the glass. None before a screen is built
        if not self.__screens:
            return None

        return min(screen.framerate for screen in self.__screens)

    def __register(self, screen):
        self.__screens.append(screen)

    def __check_cs(self, pin=None):
        # Resolve a screen's CS line and refuse a line already spoken for. None takes the
        # port's own, which is the first screen's to have, and every further screen needs
        # its own, since CS is the only signal selecting one panel
        if pin is None:
            pin = self.cs

        if pin in self.__cs_claimed:
            raise ValueError(f"{self.label} already has a screen on {pin}. Every "
                             "further screen on a port needs a cs of its own.")

        return pin

    def __claim_cs(self, pin):
        self.__cs_claimed.append(pin)

    def __check_dc(self, pin=None, te=True, shared=False):
        # Resolve a screen's DC line and refuse a line whose TE it would spoil. None takes
        # the port's own, which is the first screen's to have, and passing this port's dc
        # shares that line deliberately. Panels using TE may share it only where every one
        # names that same line as its te, which declares the diode per breakout that the
        # firmware cannot see and without which no asserted level survives.
        if pin is None:
            pin = self.dc
            if any(claimed is pin for claimed, _, _ in self.__dc_claimed):
                raise ValueError(f"{self.label}'s own DC line is taken. Give this "
                                 "screen a dc, or pass the port's dc to share that line.")

        for claimed, claimed_te, claimed_shared in self.__dc_claimed:
            if claimed is not pin:
                continue
            if (te and not shared) or (claimed_te and not claimed_shared):
                raise ValueError(f"{pin} is carrying TE for another screen. Screens "
                                 "sharing a DC line all need te=False, or te set to that "
                                 "line on every one of them, which needs a diode fitted "
                                 "to each breakout.")

        return pin

    def __claim_dc(self, pin, te, shared):
        self.__dc_claimed.append((pin, te, shared))

    def __claim_backlight(self):
        # The port's backlight, created for the first screen to ask for it. The port
        # carries one BL line, so every screen taking it shares the setting, and where no
        # screen claims it the pin is left alone, free to be a CS or DC
        if self.__backlight is None:
            self.__backlight = Backlight(self, self.bl)

        return self.__backlight

    def backlight_off(self):
        """Take the port's backlight dark, doing nothing where no screen claimed it."""
        if self.__backlight is not None:
            self.__backlight.off()

    def stop_panels(self):
        """Take every panel on this port dark and asleep, each over its own chip select.

        Ahead of release(), a pin handed back being unable to carry a command. A frame
        left staged owns DC, so it is abandoned first, nothing being bound for the glass
        after this anyway.
        """
        for screen in self.__screens:
            screen.__display.abort_frame()
            screen.CONTROLLER.stop(screen.__display)

    def release(self):
        """Hand back the bus's DMA channel and its screens' SRAM claims, and stop
        driving the port's lines.

        Nothing else gives these up early, and with 16 DMA channels and a PSRAM heap
        that is rarely collected, a program building screens repeatedly runs out and
        the SDK panics. Afterwards this port's screens report rather than transfer, a
        second call does nothing, and the port is free to be built on again, which is
        the case this exists for. Canvases are not given back, the other port's
        screens may still be drawing to them, so shutdown() does that.
        """
        for screen in self.__screens:
            screen.__display.__del__()
        self.__screens.clear()

        # The CS and DC claims name screens that are gone and lines handed back below,
        # so they go too and a port built on again starts from nothing
        self.__cs_claimed.clear()
        self.__dc_claimed.clear()

        # The backlight is holding those screens too. It keeps its level and its lit
        # state, a line that is up staying up rather than blinking over a rebuild
        if self.__backlight is not None:
            self.__backlight.__forget_screens()

        # Dropped as well as deleted, so the next screen on this port is made a fresh
        # bus with a channel of its own
        if self.__spi_bus is not None:
            self.__spi_bus.__del__()
            self.__spi_bus = None

        # A display leaves its chip select and DC driven high, which is right while
        # anything may still transmit and wrong once nothing will. Whatever is plugged in
        # next meets the level these pins were left at, and high on a screen's BL lights
        # its backlight before that thing's own code has run. Pulled down is a cold
        # boot's own state at the pin.
        for pin in self.__pins[:4]:     # The BL stays, backlight_off() putting it out
            pin.init(Pin.IN, Pin.PULL_DOWN)

    def shutdown(self):
        """Take the port down, backlight out, panels asleep, then release().

        Canvases are left, since another port's screens may still draw to them.
        spidisplay.release_buffers() gives those back once every port is down.
        """
        self.backlight_off()
        self.stop_panels()
        self.release()


def shutdown(*ports):
    """Take every port down and give the canvases back, as a board's shutdown does."""
    for port in ports:
        port.shutdown()
    release_buffers()
