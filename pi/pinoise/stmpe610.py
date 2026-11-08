"""Polled STMPE610 on SPI0 CS1; leaves TFT CS0 and IRQ wiring untouched.

Register meanings follow the STMPE610 datasheet. The adapter deliberately does
not enable the interrupt pin, which conflicts with display reset on some clones.
"""

import logging
import time
from .touch import Mapping

LOG = logging.getLogger("pinoise")


class STMPE610:
    def __init__(self, bounds=None, rotation=0, invert_x=False, invert_y=False, spi_factory=None):
        self.mapping = Mapping(bounds or (0, 4095, 0, 4095), rotation, invert_x, invert_y)
        if spi_factory is None:
            import spidev

            spi_factory = spidev.SpiDev
        self.spi = spi_factory()
        self.start = self.point = None
        self.invalid = False
        self.last = -1.0
        self.discard = False
        try:
            self.spi.open(0, 1)
            self.spi.max_speed_hz = 500000
            self.spi.mode = 0
            chip = (self.read(0) << 8) | self.read(1)
            if chip != 0x0811:
                raise OSError("STMPE610 chip ID mismatch: %04x" % chip)
            self.write(0x03, 2)
            time.sleep(0.01)
            self.write(0x04, 0)  # ADC and touchscreen clocks.
            self.write(0x20, 0x68)
            time.sleep(0.002)  # 96 clocks, 12-bit ADC.
            for reg, value in (
                (0x21, 2),
                (0x41, 0xA4),
                (0x56, 6),
                (0x4A, 1),
                (0x4B, 1),
                (0x4B, 0),
                (0x58, 1),
                (0x0A, 0),
                (0x09, 0),
                (0x0B, 255),
                (0x40, 1),
            ):
                self.write(reg, value)
            LOG.info("STMPE610 touch connected on SPI0 CS1, chip=%04x", chip)
        except BaseException:
            self.close()
            raise

    def read(self, reg):
        return self.spi.xfer2([reg | 128, 0])[1]

    def write(self, reg, value):
        self.spi.xfer2([reg & 127, value])

    def taps(self, now):
        if self.spi is None:
            return []
        try:
            if self.read(0x4B) & 0xC0:
                self.write(0x4B, 1)
                self.write(0x4B, 0)
                self.discard = True
                self.start = self.point = None
            count = min(128, self.read(0x4C))
            for _ in range(count):
                a, b, c, pressure = (self.read(0x57) for _ in range(4))
                point = self.mapping.point((a << 4) | (b >> 4), ((b & 15) << 8) | c)
                if self.discard:
                    continue
                if point is None or pressure == 0:
                    self.invalid = True
                    continue
                if self.start is None:
                    self.start = point
                if max(abs(point[i] - self.start[i]) for i in (0, 1)) > 18:
                    self.invalid = True
                self.point = point
            if self.read(0x40) & 128:
                return []
            # No contact: release any completed FIFO gesture, at most once.
            result = []
            if (
                not self.discard
                and not self.invalid
                and self.point is not None
                and now - self.last >= 0.4
            ):
                result = [self.point]
                self.last = now
                LOG.debug("Touch released at %s", self.point)
            self.start = self.point = None
            self.invalid = False
            self.discard = False
            return result
        except OSError as error:
            LOG.warning("STMPE610 touch disabled: %s", error)
            self.close()
            return []

    def close(self):
        if self.spi is not None:
            self.spi.close()
            self.spi = None
