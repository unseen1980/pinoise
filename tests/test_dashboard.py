import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))
from pinoise import display


class DashboardTests(unittest.TestCase):
    def snapshot(self):
        return dict(
            status="OK",
            slow_db=48.6,
            reported_db=65.0,
            max_slow_db=95,
            presentation_smoothed=True,
            display_label="HH06 SMOOTHED",
        )

    def test_main_screen_compact_gauge_and_large_history(self):
        self.assertTrue(hasattr(display, "DASHBOARD_GRAPH"), "dashboard geometry missing")
        x0, y0, x1, y1 = display.DASHBOARD_GRAPH
        self.assertGreaterEqual(y1 - y0, 60)
        self.assertLess(display.DIAL_RADIUS, 75)
        display.dashboard_background.cache_clear()
        with patch.object(display, "text", wraps=display.text) as text:
            image = display.render(self.snapshot(), [(20, 44.2), (70, 62.8), (100, 48.6)], 100)
        labels = [c.args[2] for c in text.call_args_list]
        for expected in ("MIN 44.2", "MAX 62.8", "LAST 90s", "-90s", "-45s", "NOW", "LIVE"):
            self.assertIn(expected, labels)
        self.assertNotIn("RAW 65.0", labels)
        self.assertNotIn("MAX 95.0", labels)
        self.assertEqual(image.size, (320, 240))

    def test_statistics_use_visible_time_window_not_old_or_future_values(self):
        self.assertTrue(hasattr(display, "history_range"), "visible-window statistics missing")
        self.assertEqual(
            display.history_range([(0, 90), (10, 45), (50, None), (100, 62), (101, 99)], 100, 90),
            (45, 62),
        )
        self.assertEqual(display.history_range([(0, 90), (50, None)], 100, 10), (None, None))

    def test_offline_hides_old_value_needle_and_statistics(self):
        snap = self.snapshot()
        snap.update(status="SENSOR OFFLINE", slow_db=None)
        with patch.object(display, "text", wraps=display.text) as text:
            image = display.render(snap, [(99, 48)], 100, needle=48)
        labels = [c.args[2] for c in text.call_args_list]
        self.assertIn("OFFLINE", labels)
        self.assertIn("MIN --", labels)
        self.assertIn("MAX --", labels)
        self.assertIn("--", labels)
        self.assertNotIn("LIVE", labels)
        self.assertEqual(image.size, (320, 240))

    def test_graph_breaks_at_gaps_and_does_not_plot_future_points(self):
        from PIL import Image, ImageDraw

        a = Image.new("RGB", (320, 240), display.BG)
        b = a.copy()
        display.graph(
            ImageDraw.Draw(a), [(15, 50), (16, None), (17, 70)], 100, 90, (30, 160, 308, 220)
        )
        display.graph(
            ImageDraw.Draw(b),
            [(15, 50), (16, None), (17, 70), (101, 90)],
            100,
            90,
            (30, 160, 308, 220),
        )
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_labels_fit_frame_in_normal_and_error_states(self):
        states = ["OK", "SENSOR OFFLINE", "BELOW RANGE", "ABOVE RANGE"]
        for state in states:
            snap = self.snapshot()
            snap["status"] = state
            if state != "OK":
                snap["slow_db"] = None
            for value in (40, 99.9, 130):
                if state == "OK":
                    snap["slow_db"] = value
                with patch.object(display, "text", wraps=display.text) as text:
                    display.render(snap, [(99, value)], 100)
                for c in text.call_args_list:
                    _, (x, y), content, size, fill = c.args
                    tile, (dx, dy) = display.glyph(content, size, fill)
                    self.assertGreaterEqual(x + dx, 0, content)
                    self.assertLessEqual(x + dx + tile.width, 320, content)
                    self.assertLessEqual(y + dy + tile.height, 240, content)


if __name__ == "__main__":
    unittest.main()
