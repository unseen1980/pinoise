import json
import os
import pathlib
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))
try:
    from pinoise.runtime import Broker
    from pinoise.display import render
except ImportError:
    Broker = None


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Broker, "runtime adapters missing")

    def test_socket_stream_is_production_measurement(self):
        with tempfile.TemporaryDirectory() as d:
            broker = Broker(d + "/stream.sock", {"profile": None})
            broker.start()
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(2)
            client.connect(d + "/stream.sock")
            with client.makefile("r") as f:
                self.assertEqual(json.loads(f.readline())["kind"], "hello")
                broker.publish({"kind": "measurement", "slow_db": 63.2})
                self.assertEqual(json.loads(f.readline())["slow_db"], 63.2)
            client.close()
            broker.close()
            self.assertFalse(os.path.exists(d + "/stream.sock"))

    def test_framebuffer_color_encoding(self):
        from PIL import Image
        import pinoise.display as display

        self.assertTrue(hasattr(display, "pack_rgb565"), "native color packer missing")
        image = Image.new("RGB", (5, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)])
        self.assertEqual(display.pack_rgb565(image), bytes.fromhex("00f8e0071f00ffff0000"))

    def test_all_display_states_render(self):
        for status in ("BELOW RANGE", "ABOVE RANGE", "SENSOR OFFLINE", "OK"):
            image = render(
                {
                    "status": status,
                    "slow_db": 60.0 if status == "OK" else None,
                    "max_slow_db": 64.0 if status == "OK" else None,
                },
                [(1, None), (2, 50.0)],
                now=3,
            )
            self.assertEqual(image.size, (320, 240))

    def test_capture_waits_for_delayed_service_socket(self):
        import subprocess

        with tempfile.TemporaryDirectory() as d:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(pathlib.Path(__file__).resolve().parents[1] / "pi/capture.py"),
                    "--socket",
                    d + "/s",
                    "--duration",
                    ".1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.3)
            broker = Broker(d + "/s", {})
            broker.start()
            try:
                out, err = process.communicate(timeout=4)
                self.assertEqual(process.returncode, 0, err.decode())
                self.assertEqual(json.loads(out.splitlines()[0])["kind"], "hello")
            finally:
                broker.close()

    def test_duplicate_start_cannot_remove_active_socket(self):
        with tempfile.TemporaryDirectory() as d:
            a = Broker(d + "/s", {})
            b = Broker(d + "/s", {})
            a.start()
            try:
                with self.assertRaises(RuntimeError):
                    b.start()
                b.close()
                self.assertTrue(os.path.exists(d + "/s"))
            finally:
                a.close()


if __name__ == "__main__":
    unittest.main()
