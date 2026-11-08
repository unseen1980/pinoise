import importlib.util
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("pinoise.presentation"), "smoothed view missing"
        )
        from pinoise.presentation import SmoothedView

        self.view = SmoothedView()

    def sample(self, value, t):
        return dict(
            source="hh0603",
            status="OK",
            slow_db=value,
            reported_db=value,
            received_mono=t,
            max_slow_db=90,
        )

    def test_isolated_spike_does_not_change_main_value_or_raw(self):
        for t in (0, 0.5, 1):
            self.view.update(self.sample(50, t), t)
        snap = self.sample(65, 1.5)
        shown, _ = self.view.update(snap, 1.5)
        self.assertEqual(shown["slow_db"], 50)
        self.assertEqual(shown["reported_db"], 65)
        self.assertEqual(snap["slow_db"], 65)
        self.assertEqual(shown["display_label"], "HH06 SMOOTHED")
        self.assertEqual(shown["max_slow_db"], 50)

    def test_sustained_rise_and_fall_not_suppressed(self):
        for t in (0, 0.5, 1):
            self.view.update(self.sample(50, t), t)
        for t in (1.5, 2, 2.5, 3):
            shown, _ = self.view.update(self.sample(70, t), t)
        self.assertGreater(shown["slow_db"], 68)
        for t in (3.5, 4, 4.5, 5, 5.5):
            shown, _ = self.view.update(self.sample(50, t), t)
        self.assertLess(shown["slow_db"], 52)

    def test_render_ticks_do_not_count_as_sensor_samples(self):
        for t in (0, 0.5, 1):
            self.view.update(self.sample(50, t), t)
        spike = self.sample(80, 1.5)
        for now in (1.5, 1.6, 1.7, 1.8, 1.9):
            shown, _ = self.view.update(spike, now)
        self.assertEqual(shown["slow_db"], 50)

    def test_offline_resets_and_preserves_graph_gap(self):
        self.view.update(self.sample(80, 1), 1)
        shown, h = self.view.update(dict(status="SENSOR OFFLINE", slow_db=None), 3)
        self.assertIsNone(shown["slow_db"])
        self.assertIsNone(h[-1][1])
        shown, _ = self.view.update(self.sample(45, 4), 4)
        self.assertEqual(shown["slow_db"], 45)

    def out_of_range(self, t, status="BELOW RANGE", reported=39.5):
        # Exactly what Meter.consume() produces for a valid packet outside 40-130 dB.
        return dict(
            source="hh0603",
            status=status,
            slow_db=None,
            reported_db=reported,
            received_mono=t,
            max_slow_db=None,
        )

    def test_isolated_out_of_range_reading_is_an_excursion_not_an_outage(self):
        for t in (0, 0.5, 1):
            self.view.update(self.sample(41, t), t)
        for status, reported in (("BELOW RANGE", 39.5), ("ABOVE RANGE", 131)):
            shown, h = self.view.update(self.out_of_range(1.5, status, reported), 1.5)
            self.assertEqual(shown["slow_db"], 41)
            self.assertEqual(shown["status"], "OK")
            self.assertEqual(shown["raw_status"], status)
            self.assertEqual(h[-1][1], 41)
            self.view.update(self.sample(41, 2), 2)
            self.setUp()
            [self.view.update(self.sample(41, t), t) for t in (0, 0.5, 1)]

    def test_floor_hovering_readings_do_not_flicker(self):
        shown_values = []
        for i in range(20):
            t = i * 0.5
            snap = self.sample(41, t) if i % 2 == 0 else self.out_of_range(t)
            shown, h = self.view.update(snap, t)
            shown_values.append(shown["slow_db"])
        self.assertNotIn(None, shown_values)
        self.assertNotIn(None, [v for _, v in h])
        self.assertTrue(all(v >= 40 for v in shown_values))

    def test_sustained_out_of_range_hides_value_and_breaks_graph(self):
        from pinoise.display import render

        for t in (0, 0.5, 1):
            self.view.update(self.sample(41, t), t)
        self.view.update(self.out_of_range(1.5), 1.5)
        shown, h = self.view.update(self.out_of_range(2), 2)
        self.assertIsNone(shown["slow_db"])
        self.assertEqual(shown["status"], "BELOW RANGE")
        self.assertIsNone(h[-1][1])
        for detail in (False, True):
            self.assertEqual(render(shown, h, 2, graph_view=detail).size, (320, 240))
        shown, _ = self.view.update(self.sample(47, 2.5), 2.5)
        self.assertEqual(shown["slow_db"], 47)

    def test_out_of_range_at_startup_shows_no_number(self):
        shown, _ = self.view.update(self.out_of_range(0), 0)
        self.assertIsNone(shown["slow_db"])
        self.assertEqual(shown["status"], "BELOW RANGE")

    def test_render_ticks_do_not_count_out_of_range_twice(self):
        for t in (0, 0.5, 1):
            self.view.update(self.sample(41, t), t)
        below = self.out_of_range(1.5)
        for now in (1.5, 1.6, 1.7, 1.8, 1.9):
            shown, _ = self.view.update(below, now)
        self.assertEqual(shown["slow_db"], 41)

    def test_detail_view_never_prints_out_of_range_raw_as_a_number(self):
        from unittest.mock import patch
        from pinoise.display import render

        for t in (0, 0.5, 1):
            self.view.update(self.sample(41, t), t)
        shown, h = self.view.update(self.out_of_range(1.5), 1.5)
        with patch("pinoise.display.text") as text:
            render(shown, h, 1.5, graph_view=True)
        contents = [c.args[2] for c in text.call_args_list]
        self.assertIn("RAW BELOW RANGE", contents)
        self.assertNotIn("RAW 39.5", contents)

    def test_display_exposes_raw_and_smoothed_labels(self):
        from unittest.mock import patch
        from pinoise.display import render

        shown, h = self.view.update(self.sample(55, 1), 1)
        with patch("pinoise.display.text") as text:
            render(shown, h, 1, graph_view=True)
        contents = [c.args[2] for c in text.call_args_list]
        self.assertIn("RAW 55.0", contents)
        self.assertIn("HH06 SMOOTHED", contents)


if __name__ == "__main__":
    unittest.main()
