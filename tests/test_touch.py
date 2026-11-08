import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))


class TouchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("pinoise.touch"), "coordinate-aware touch reader missing"
        )
        from pinoise import touch

        self.t = touch

    def events(self, *values):
        return b"".join(self.t.EVENT.pack(0, 0, *v) for v in values)

    def gesture(self, x=290, y=216):
        return self.events((3, 0, x), (3, 1, y), (1, 330, 1), (0, 0, 0), (1, 330, 0), (0, 0, 0))

    def test_mapping_ranges_rotation_inversion_and_invalid_coordinates(self):
        m = self.t.Mapping((100, 3900, 200, 3800))
        self.assertEqual(m.point(100, 200), (0, 0))
        self.assertEqual(m.point(3900, 3800), (319, 239))
        self.assertIsNone(m.point(0, 200))
        self.assertEqual(self.t.Mapping((0, 4095, 0, 4095), rotation=90).point(0, 0), (319, 0))
        self.assertEqual(self.t.Mapping((0, 4095, 0, 4095), rotation=180).point(0, 0), (319, 239))
        self.assertEqual(self.t.Mapping((0, 4095, 0, 4095), rotation=270).point(0, 0), (0, 239))
        self.assertEqual(
            self.t.Mapping((0, 4095, 0, 4095), invert_x=True, invert_y=True).point(0, 0), (319, 239)
        )
        with self.assertRaises(ValueError):
            self.t.Mapping((100, 100, 0, 100))

    def test_split_reads_require_complete_press_release_and_syn(self):
        stream = self.t.TouchStream(self.t.Mapping((0, 319, 0, 239)))
        data = self.gesture()
        self.assertEqual(stream.feed(data[:9], 1), [])
        self.assertEqual(stream.feed(data[9 : -self.t.EVENT.size], 1), [])
        self.assertEqual(stream.feed(data[-self.t.EVENT.size :], 1), [(290, 216)])
        self.assertEqual(stream.feed(self.events((1, 330, 0), (0, 0, 0)), 2), [])

    def test_measured_clone_mapping_hits_power_and_cancel(self):
        from pinoise.controls import Controls

        mapping = self.t.Mapping((258, 3820, 191, 3724), rotation=90)
        ui = Controls()
        ui.tap((160, 120), 0)
        # Representative raw readings at the physically labelled corner targets.
        for raw, expected in (((735, 3370), (32, 32)), ((3358, 535), (288, 208))):
            point = mapping.point(*raw)
            self.assertLess(max(abs(point[i] - expected[i]) for i in (0, 1)), 4)
        ui.tap(mapping.point(3358, 535), 1)
        self.assertEqual(ui.state, "confirm")
        # The old unrotated mapping placed this bottom-left tap at top-right.
        ui.tap(mapping.point(2765, 2874), 2)
        self.assertEqual(ui.state, "normal")
        self.assertTrue(ui.detail)

    def test_missing_coordinates_drag_and_out_of_bounds_cannot_tap(self):
        stream = self.t.TouchStream(self.t.Mapping((0, 319, 0, 239)))
        self.assertEqual(stream.feed(self.events((1, 330, 1), (1, 330, 0), (0, 0, 0)), 1), [])
        data = self.events(
            (3, 0, 20),
            (3, 1, 20),
            (1, 330, 1),
            (0, 0, 0),
            (3, 0, 250),
            (0, 0, 0),
            (3, 0, 20),
            (1, 330, 0),
            (0, 0, 0),
        )
        self.assertEqual(stream.feed(data, 2), [])
        self.assertEqual(stream.feed(self.gesture(400, 200), 3), [])

    def test_bounce_and_queued_double_taps_are_ignored(self):
        stream = self.t.TouchStream(self.t.Mapping((0, 319, 0, 239)))
        self.assertEqual(stream.feed(self.gesture() + self.gesture(), 1), [(290, 216)])
        self.assertEqual(stream.feed(self.gesture(), 1.1), [])
        self.assertEqual(stream.feed(self.gesture(), 2), [(290, 216)])

    def test_dropped_event_sequence_needs_release_then_new_gesture(self):
        stream = self.t.TouchStream(self.t.Mapping((0, 319, 0, 239)))
        data = self.events(
            (3, 0, 290), (3, 1, 216), (1, 330, 1), (0, 0, 0), (0, 3, 0), (1, 330, 0), (0, 0, 0)
        )
        self.assertEqual(stream.feed(data, 1), [])
        self.assertEqual(stream.feed(self.events((1, 330, 0), (0, 0, 0)), 2), [])
        self.assertEqual(stream.feed(self.gesture(), 3), [(290, 216)])

    def test_device_detection_ioctl_ranges_and_polling(self):
        def ioctl(fd, request, data):
            if request & 255 in (0x40, 0x41):
                maximum = 319 if request & 255 == 0x40 else 239
                return self.t.ABSINFO.pack(0, 0, maximum, 0, 0, 0)
            keys = bytearray(64)
            keys[330 // 8] |= 1 << (330 % 8)
            return bytes(keys)

        with (
            patch.object(self.t.os, "open", return_value=7),
            patch.object(self.t.os, "close") as close,
            patch.object(self.t.fcntl, "ioctl", side_effect=ioctl),
            patch.object(self.t.select, "select", side_effect=[([7], [], []), ([], [], [])]),
            patch.object(self.t.os, "read", return_value=self.gesture()),
        ):
            touch = self.t.Touch("/dev/input/event0")
            self.assertEqual(touch.taps(1), [(290, 216)])
            touch.close()
            touch.close()
            close.assert_called_once_with(7)

    def test_unusable_device_is_closed_and_touch_is_optional(self):
        with (
            patch.object(self.t.os, "open", return_value=7),
            patch.object(self.t.os, "close") as close,
            patch.object(self.t.fcntl, "ioctl", side_effect=OSError("not touch")),
            self.assertLogs("pinoise", level="WARNING"),
        ):
            touch = self.t.Touch("/dev/input/event0")
            self.assertEqual(touch.taps(1), [])
            close.assert_called_once_with(7)

    def test_read_failure_disables_touch_without_stopping_gauge(self):
        touch = self.t.Touch.__new__(self.t.Touch)
        touch.fd = 7
        touch.stream = self.t.TouchStream(self.t.Mapping((0, 319, 0, 239)))
        with (
            patch.object(self.t.os, "close") as close,
            patch.object(self.t.select, "select", return_value=([7], [], [])),
            patch.object(self.t.os, "read", side_effect=OSError("removed")),
            self.assertLogs("pinoise", level="WARNING"),
        ):
            self.assertEqual(touch.taps(1), [])
            self.assertIsNone(touch.fd)
            close.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
