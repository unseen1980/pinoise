"""Publication boundaries and supported application entry point."""

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_application_exposes_only_supported_sensor_options(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "pi/noise_gauge.py"), "--help"],
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertNotIn("--profile", result.stdout)
        self.assertNotIn("--sensor", result.stdout)
        self.assertIn("--serial", result.stdout)

    def test_runtime_modules_are_self_contained(self):
        modules = {p.stem for p in (ROOT / "pi/pinoise").glob("*.py")}
        self.assertEqual(
            modules,
            {
                "__init__",
                "hh0603",
                "runtime",
                "presentation",
                "display",
                "touch",
                "controls",
                "stmpe610",
            },
        )

    def test_ci_tests_every_supported_python_on_an_available_runner(self):
        workflow = (ROOT / ".github/workflows/tests.yml").read_text()
        runners = [
            line.split(":", 1)[1].strip()
            for line in workflow.splitlines()
            if line.strip().startswith("runs-on:")
        ]
        # The floating latest label moved to an image without Python 3.9.
        self.assertEqual(runners, ["ubuntu-24.04"])
        self.assertIn("fail-fast: false", workflow)
        self.assertIn("'3.9'", workflow)  # Raspberry Pi OS 11 ships Python 3.9

    def test_service_is_sandboxed_but_keeps_device_and_poweroff_access(self):
        unit = dict(
            line.split("=", 1)
            for line in (ROOT / "pi/noise_gauge.service").read_text().splitlines()
            if "=" in line and not line.startswith("#")
        )
        for key, value in (
            ("ProtectSystem", "strict"),
            ("ProtectHome", "yes"),
            ("PrivateTmp", "yes"),
            ("NoNewPrivileges", "true"),
            ("RestrictAddressFamilies", "AF_UNIX"),
            ("ProtectKernelModules", "yes"),
            ("ProtectKernelTunables", "yes"),
        ):
            self.assertEqual(unit.get(key), value, key)
        # Hardware is reached through /dev; isolating it would break UART, TFT and touch.
        for key in ("PrivateDevices", "ProtectClock", "DevicePolicy", "DeviceAllow"):
            self.assertNotIn(key, unit)
        self.assertEqual(unit["RuntimeDirectory"], "pinoise")


if __name__ == "__main__":
    unittest.main()
