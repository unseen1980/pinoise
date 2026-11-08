import importlib.util
import json
import os
import pathlib
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pi"))
from pinoise.runtime import Broker
from pinoise.display import render


def packet(value, command=1):
    body = bytes((0xBB, 0xAA, command, value & 255, value >> 8))
    return body + bytes((sum(body) & 255,))


class HH0603Tests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("pinoise.hh0603"), "HH_06.03 production adapter missing"
        )
        from pinoise import hh0603

        self.hh = hh0603

    def test_fragmented_packets_checksum_resync_and_version(self):
        decoder = self.hh.Decoder()
        self.assertEqual(decoder.feed(b"junk\xbb"), [])
        frames = decoder.feed(packet(2, 0)[1:] + packet(639)[:4])
        self.assertEqual(frames[0].command, 0)
        self.assertIsNone(frames[0].db)
        frames = decoder.feed(packet(639)[4:])
        self.assertEqual(frames[0].db, 63.9)
        self.assertEqual(frames[0].raw, bytes.fromhex("bb aa 01 7f 02 e7"))
        broken = bytearray(packet(500))
        broken[-1] ^= 1
        self.assertEqual([f.db for f in decoder.feed(bytes(broken) + packet(701))], [70.1])
        self.assertEqual(decoder.rejected, 1)
        self.assertEqual(decoder.feed(b"x" * 10000), [])
        self.assertLessEqual(len(decoder.buffer), 5)

    def test_reported_db_is_unchanged_and_stales(self):
        meter = self.hh.Meter()
        self.assertIsNone(meter.snapshot(0)["slow_db"])
        decoder = self.hh.Decoder()
        for t, value in ((1, 450), (1.5, 820), (2, 500)):
            event = meter.consume(decoder.feed(packet(value))[0], t)
            self.assertEqual(event["slow_db"], value / 10)
            self.assertEqual(event["reported_db"], value / 10)
            self.assertEqual(event["source"], "hh0603")
            self.assertFalse(event["validated"])
            self.assertNotIn("frame", event)  # no synthetic ADC samples
        self.assertEqual(meter.snapshot(2)["max_slow_db"], 82)
        self.assertIsNone(meter.snapshot(4)["slow_db"])
        self.assertEqual(meter.snapshot(4)["status"], "SENSOR OFFLINE")
        meter.disconnected(2.1)
        self.assertIsNone(meter.snapshot(2.1)["slow_db"])
        event = meter.consume(decoder.feed(packet(480))[0], 4.1)
        self.assertEqual(event["max_slow_db"], 48)

    def test_snapshot_is_constant_size_and_keeps_no_unused_history(self):
        meter = self.hh.Meter()
        decoder = self.hh.Decoder()
        end = time.monotonic()
        for i in range(3000):
            meter.consume(decoder.feed(packet(500))[0], end - (2999 - i) * 0.5)
        source = self.hh.Acquisition("/dev/null", meter, lambda event: None)
        snap = source.snapshot()
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap["slow_db"], 50)
        self.assertFalse(hasattr(meter, "history"))
        self.assertLessEqual(len(meter.recent), 9)

    def test_outside_documented_range_is_not_displayed_as_valid(self):
        meter = self.hh.Meter()
        decoder = self.hh.Decoder()
        for n, status in ((399, "BELOW RANGE"), (1301, "ABOVE RANGE")):
            event = meter.consume(decoder.feed(packet(n))[0], 1)
            self.assertEqual(event["status"], status)
            self.assertIsNone(event["slow_db"])
            self.assertEqual(event["reported_db"], n / 10)
        for n in (400, 1300):
            self.assertEqual(meter.consume(decoder.feed(packet(n))[0], 2)["slow_db"], n / 10)

    def test_real_uart_to_broker_and_display(self):
        import pty

        master, slave = pty.openpty()
        source = None
        try:
            with tempfile.TemporaryDirectory() as directory:
                broker = Broker(directory + "/s", {"source": "hh0603"})
                broker.start()
                client = socket.socket(socket.AF_UNIX)
                client.settimeout(3)
                client.connect(directory + "/s")
                try:
                    with client.makefile("r") as stream:
                        self.assertEqual(json.loads(stream.readline())["source"], "hh0603")
                        source = self.hh.Acquisition(
                            os.ttyname(slave), self.hh.Meter(), broker.publish
                        )
                        source.start()
                        deadline = time.monotonic() + 2
                        while source.serial is None and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertIsNotNone(source.serial)
                        self.assertEqual(source.serial.baudrate, 115200)
                        os.write(master, packet(2, 0) + packet(639)[:3])
                        time.sleep(0.03)
                        os.write(master, packet(639)[3:])
                        event = json.loads(stream.readline())
                        self.assertEqual(event["reported_db"], 63.9)
                        self.assertEqual(event["sensor_firmware"], "2.0")
                        self.assertEqual(event["raw_hex"], "bbaa017f02e7")
                        snap = source.snapshot()
                        self.assertEqual(snap["slow_db"], 63.9)
                        now = time.monotonic()
                        self.assertEqual(render(snap, [(now, 63.9)], now).size, (320, 240))
                finally:
                    if source:
                        source.close()
                    client.close()
                    broker.close()
            self.assertIsNone(source.fatal)
        finally:
            os.close(master)
            os.close(slave)

    def test_service_entrypoint_reads_module_directly(self):
        import pty
        import subprocess

        master, slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory() as directory:
                script = pathlib.Path(__file__).resolve().parents[1] / "pi/noise_gauge.py"
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(script),
                        "--headless",
                        "--serial",
                        os.ttyname(slave),
                        "--socket",
                        directory + "/s",
                        "--duration",
                        "1.5",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    deadline = time.monotonic() + 3
                    while not os.path.exists(directory + "/s") and time.monotonic() < deadline:
                        time.sleep(0.01)
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(3)
                        client.connect(directory + "/s")
                        with client.makefile("r") as stream:
                            hello = json.loads(stream.readline())
                            self.assertEqual(hello["source"], "hh0603")
                            self.assertNotIn("profile", hello)
                            time.sleep(0.1)
                            os.write(master, packet(715))
                            event = json.loads(stream.readline())
                            self.assertEqual(event["slow_db"], 71.5)
                    _, err = process.communicate(timeout=4)
                    self.assertEqual(process.returncode, 0, err.decode())
                    self.assertNotIn(b"UNCALIBRATED", err)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdout.close()
                    process.stderr.close()
        finally:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
