import importlib.util
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("pinoise.controls"), "safe shutdown controller missing"
        )
        from pinoise import controls

        self.c = controls

    def test_navigation_confirmation_cancel_and_timeout(self):
        ui = self.c.Controls()
        ui.tap((290, 216), 0)  # Main dashboard never shuts down.
        self.assertTrue(ui.detail)
        self.assertEqual(ui.state, "normal")
        ui.tap((290, 216), 1)
        self.assertEqual(ui.state, "confirm")
        ui.tap((240, 165), 1.1)  # Opening tap/double tap cannot confirm.
        self.assertEqual(ui.state, "confirm")
        ui.tap((160, 110), 2)  # Outside buttons does nothing.
        self.assertEqual(ui.state, "confirm")
        ui.tap((75, 165), 3)
        self.assertEqual(ui.state, "normal")
        self.assertTrue(ui.detail)
        ui.tap((290, 216), 4)
        ui.tick(20)
        self.assertEqual(ui.state, "normal")
        ui.tap((10, 100), 21)
        self.assertFalse(ui.detail)

    def test_shutdown_requires_confirmation_and_is_dispatched_once(self):
        calls = []
        ui = self.c.Controls()
        ui.dispatch(lambda: calls.append("poweroff"))
        self.assertEqual(calls, [])
        ui.tap((10, 100), 0)
        ui.tap((290, 216), 1)
        ui.tap((240, 165), 2)
        self.assertEqual(ui.state, "pending")
        ui.dispatch(lambda: calls.append("poweroff"))
        self.assertEqual(ui.state, "shutting_down")
        ui.tap((75, 165), 3)
        ui.dispatch(lambda: calls.append("again"))
        self.assertEqual(calls, ["poweroff"])

    def test_failed_request_requires_new_confirmation(self):
        ui = self.c.Controls()
        ui.tap((10, 100), 0)
        ui.tap((290, 216), 1)
        ui.tap((240, 165), 2)

        def fail():
            raise OSError("permission denied")

        with self.assertLogs("pinoise", level="ERROR"):
            ui.dispatch(fail)
        self.assertEqual(ui.state, "failed")
        ui.tap((240, 165), 3)
        self.assertEqual(ui.state, "failed")
        ui.tap((75, 165), 4)
        self.assertEqual(ui.state, "normal")
        ui.tap((290, 216), 5)
        ui.tap((240, 165), 6)
        ui.dispatch(lambda: None)
        self.assertEqual(ui.state, "shutting_down")

    def test_poweroff_is_normal_systemd_shutdown_without_shell_or_force(self):
        with (
            patch.object(self.c.sys, "platform", "linux"),
            patch.object(self.c.os.path, "isdir", return_value=True),
            patch.object(self.c.subprocess, "run") as run,
        ):
            self.c.request_shutdown()
        run.assert_called_once_with(
            ["/usr/bin/systemctl", "--no-block", "--no-ask-password", "poweroff"],
            check=True,
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_non_pi_development_host_cannot_run_poweroff(self):
        with (
            patch.object(self.c.sys, "platform", "darwin"),
            patch.object(self.c.subprocess, "run") as run,
        ):
            with self.assertRaises(OSError):
                self.c.request_shutdown()
            run.assert_not_called()

    def test_dialog_renders_all_states_with_fitting_labels(self):
        from pinoise import display

        self.assertTrue(hasattr(display, "render_controls"), "shutdown dialog renderer missing")
        for state in ("confirm", "pending", "shutting_down", "failed"):
            with patch.object(display, "text", wraps=display.text) as text:
                image = display.render_controls(state)
            self.assertEqual(image.size, (320, 240))
            labels = [c.args[2] for c in text.call_args_list]
            self.assertNotIn("Safe to unplug", labels)
            for c in text.call_args_list:
                _, (x, y), content, size, fill = c.args
                tile, (dx, dy) = display.glyph(content, size, fill)
                self.assertGreaterEqual(x + dx, 0)
                self.assertLessEqual(x + dx + tile.width, 320, content)
                self.assertLessEqual(y + dy + tile.height, 240, content)
        with patch.object(display, "text", wraps=display.text) as text:
            display.render_controls("confirm")
        labels = [c.args[2] for c in text.call_args_list]
        for label in ("Shut down Raspberry Pi?", "Cancel", "Shut down"):
            self.assertIn(label, labels)

    def test_entrypoint_paints_before_request_and_closes_resources(self):
        import noise_gauge
        from pinoise import display

        order = []
        fb = MagicMock()
        touch = MagicMock()
        source = MagicMock()
        broker = MagicMock()
        source.fatal = None
        source.snapshot.return_value = {"status": "SENSOR OFFLINE", "slow_db": None}
        source.close.side_effect = lambda: order.append("source closed")
        touch.taps.side_effect = [[(10, 100)], [(290, 216)], [(240, 165)], []]
        render_controls = display.render_controls

        def dialog(state):
            order.append(state)
            return render_controls(state)

        fb.show.side_effect = lambda image: order.append("painted")
        # Mock only OS/hardware boundaries; exercise the real controller and main loop.
        with (
            patch.object(sys, "argv", ["noise_gauge.py", "--duration", "4"]),
            patch.object(noise_gauge, "Acquisition", return_value=source),
            patch.object(noise_gauge, "Broker", return_value=broker),
            patch.object(noise_gauge, "from_arguments", return_value=touch),
            patch.object(noise_gauge.signal, "signal"),
            patch.object(noise_gauge.logging, "basicConfig"),
            patch.object(
                noise_gauge.threading, "Event", return_value=MagicMock(is_set=lambda: False)
            ),
            patch.object(noise_gauge.time, "monotonic", side_effect=[0, 1, 1, 2, 2, 3, 3, 4]),
            patch.object(display, "Framebuffer", return_value=fb),
            patch.object(display, "render_controls", side_effect=dialog),
            patch.object(self.c.sys, "platform", "linux"),
            patch.object(self.c.os.path, "isdir", return_value=True),
            patch.object(
                self.c.subprocess, "run", side_effect=lambda *a, **kw: order.append("poweroff")
            ) as run,
        ):
            self.assertEqual(noise_gauge.main(), 0)
        i = order.index("poweroff")
        self.assertEqual(order[i - 2 : i], ["pending", "painted"])
        self.assertEqual(run.call_count, 1)
        self.assertIn("shutting_down", order)
        self.assertEqual(order[-1], "source closed")
        broker.close.assert_called_once()
        fb.close.assert_called_once()
        touch.close.assert_called_once()

    def test_every_resource_is_released_when_one_close_fails(self):
        import noise_gauge
        from pinoise import display

        fb = MagicMock()
        touch = MagicMock()
        source = MagicMock()
        broker = MagicMock()
        source.fatal = None
        source.ident = 1
        source.snapshot.return_value = {"status": "SENSOR OFFLINE", "slow_db": None}
        source.close.side_effect = RuntimeError("UART reader did not stop")
        touch.taps.return_value = []
        with (
            patch.object(sys, "argv", ["noise_gauge.py", "--duration", "1"]),
            patch.object(noise_gauge, "Acquisition", return_value=source),
            patch.object(noise_gauge, "Broker", return_value=broker),
            patch.object(noise_gauge, "from_arguments", return_value=touch),
            patch.object(noise_gauge.signal, "signal"),
            patch.object(noise_gauge.logging, "basicConfig"),
            patch.object(noise_gauge.time, "monotonic", side_effect=[0, 1, 1, 2, 2]),
            patch.object(display, "Framebuffer", return_value=fb),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not stop"):
                noise_gauge.main()
        broker.close.assert_called_once()
        fb.close.assert_called_once()
        touch.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
