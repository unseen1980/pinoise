import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))


class FakeSPI:
    def __init__(self, chip=0x0811):
        self.regs = {0: chip >> 8, 1: chip & 255, 0x4B: 0, 0x40: 0}
        self.fifo = []
        self.pending = []
        self.writes = []
        self.closed = False

    def open(self, bus, device):
        self.device = (bus, device)

    def close(self):
        self.closed = True

    def xfer2(self, data):
        reg, value = data
        if reg & 128:
            reg &= 127
            if reg == 0x4C:
                return [0, len(self.fifo)]
            if reg == 0x57:
                if not self.pending:
                    x, y, z = self.fifo.pop(0)
                    self.pending = [x >> 4, ((x & 15) << 4) | (y >> 8), y & 255, z]
                return [0, self.pending.pop(0)]
            return [0, self.regs.get(reg, 0)]
        self.writes.append((reg, value))
        self.regs[reg] = value
        if reg == 0x4B and value == 1:
            self.fifo.clear()
            self.pending = []
        return [0, 0]


class STMPE610Tests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("pinoise.stmpe610"), "SPI touch adapter missing"
        )
        from pinoise import stmpe610

        self.m = stmpe610

    def touch(self, spi):
        with patch.object(self.m.time, "sleep"):
            return self.m.STMPE610(spi_factory=lambda: spi)

    def test_identifies_chip_and_only_uses_touch_chip_select(self):
        spi = FakeSPI()
        touch = self.touch(spi)
        self.assertEqual(spi.device, (0, 1))
        self.assertEqual(spi.max_speed_hz, 500000)
        self.assertIn((0x20, 0x68), spi.writes)  # 12-bit ADC
        self.assertIn((0x09, 0), spi.writes)  # IRQ output disabled: polled only.
        touch.close()
        self.assertTrue(spi.closed)
        bad = FakeSPI(0xFFFF)
        with self.assertRaises(OSError):
            self.touch(bad)
        self.assertTrue(bad.closed)
        self.assertEqual(bad.writes, [])

    def test_release_reports_tap_once_and_no_touch_does_nothing(self):
        spi = FakeSPI()
        touch = self.touch(spi)
        spi.regs[0x40] = 0
        self.assertEqual(touch.taps(0), [])
        spi.regs[0x40] = 128
        spi.fifo = [(2000, 1000, 20)]
        self.assertEqual(touch.taps(1), [])
        spi.regs[0x40] = 0
        self.assertEqual(touch.taps(1.3), [(156, 58)])
        self.assertEqual(touch.taps(2), [])

    def test_short_tap_from_fifo_and_drag_rejection(self):
        spi = FakeSPI()
        touch = self.touch(spi)
        spi.regs[0x40] = 0
        spi.fifo = [(2000, 1000, 20)]
        self.assertEqual(touch.taps(1), [(156, 58)])
        spi.fifo = [(500, 500, 20), (3500, 3500, 20)]
        self.assertEqual(touch.taps(2), [])

    def test_overflow_discards_gesture_and_read_failure_disables_touch(self):
        spi = FakeSPI()
        touch = self.touch(spi)
        spi.regs[0x4B] = 128
        spi.regs[0x40] = 128
        spi.fifo = [(2000, 1000, 20)]
        self.assertEqual(touch.taps(1), [])
        spi.regs[0x40] = 0
        self.assertEqual(touch.taps(2), [])
        with (
            patch.object(spi, "xfer2", side_effect=OSError("SPI failed")),
            self.assertLogs("pinoise", level="WARNING"),
        ):
            self.assertEqual(touch.taps(3), [])
        self.assertTrue(spi.closed)
        self.assertEqual(touch.taps(4), [])


if __name__ == "__main__":
    unittest.main()
