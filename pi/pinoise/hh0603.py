"""HH_06.03: checksum-validated, module-reported dBA at 115200 8N1.

No sensitivity profile, peak correction or additional time weighting is
applied. Internal weighting/time
response and accuracy remain the module manufacturer's claims.
"""

import collections
import dataclasses
import fcntl
import logging
import sys
import termios
import time
import threading
import serial

STALE_SECONDS = 1.5
LOG = logging.getLogger("pinoise")


@dataclasses.dataclass(frozen=True)
class Frame:
    command: int
    value: int
    raw: bytes

    @property
    def db(self):
        return self.value / 10 if self.command == 1 else None


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.rejected = 0
        self.discarded_bytes = 0

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 2:
            if self.buffer[:2] != b"\xbb\xaa":
                del self.buffer[0]
                self.discarded_bytes += 1
                continue
            if len(self.buffer) < 6:
                break
            raw = bytes(self.buffer[:6])
            if sum(raw[:5]) & 255 != raw[5] or raw[2] not in (0, 1):
                self.rejected += 1
                del self.buffer[0]
                continue
            del self.buffer[:6]
            frames.append(Frame(raw[2], raw[3] + 256 * raw[4], raw))
        return frames


class Meter:
    def __init__(self):
        # Display history lives in presentation.SmoothedView; keep only the 4 s maximum here.
        self.recent = collections.deque()
        self.received = None
        self.frames = 0
        self.firmware = None
        self.latest = dict(
            status="SENSOR OFFLINE",
            slow_db=None,
            max_slow_db=None,
            source="hh0603",
            display_label="HH06 · REPORTED",
            validated=False,
        )

    def disconnected(self, now):
        self.received = None
        self.recent.clear()
        self.latest.update(status="SENSOR OFFLINE", slow_db=None, max_slow_db=None)

    def consume(self, frame, now):
        if frame.command == 0:
            self.disconnected(now)
            self.firmware = "%d.%d" % (frame.raw[3], frame.raw[4])
            return None
        continuous = self.received is not None and 0 <= now - self.received <= STALE_SECONDS
        if not continuous:
            self.recent.clear()
        self.received = now
        self.frames += 1
        reported = frame.db
        status = "BELOW RANGE" if reported < 40 else "ABOVE RANGE" if reported > 130 else "OK"
        value = reported if status == "OK" else None
        if value is None:
            self.recent.clear()
        else:
            self.recent.append((now, value))
        while self.recent and self.recent[0][0] < now - 4:
            self.recent.popleft()
        self.latest = dict(
            schema=2,
            kind="measurement",
            source="hh0603",
            status=status,
            quality=status,
            validated=False,
            reported_db=reported,
            slow_db=value,
            max_slow_db=max((v for _, v in self.recent), default=None),
            received_mono=now,
            continuous=continuous,
            frames=self.frames,
            raw_hex=frame.raw.hex(),
            sensor_firmware=self.firmware,
            weighting="A (module specification)",
            time_weighting="unspecified",
            display_label="HH06 · REPORTED",
            timestamp_basis="host receipt; sensor integration time unknown",
        )
        return dict(self.latest)

    def snapshot(self, now):
        result = dict(self.latest)
        if self.received is None or now - self.received > STALE_SECONDS:
            result.update(status="SENSOR OFFLINE", slow_db=None, max_slow_db=None)
        result["age_s"] = None if self.received is None else max(0, now - self.received)
        return result


class Acquisition(threading.Thread):
    def __init__(self, port, meter, publish):
        super().__init__(daemon=True, name="acquisition")
        self.port, self.meter, self.publish = port, meter, publish
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.fatal = None
        self.decoder = Decoder()
        self.serial = None

    def snapshot(self):
        with self.lock:
            return self.meter.snapshot(time.monotonic())

    def close(self):
        self.stop_event.set()
        self.join(3)
        if self.is_alive():
            raise RuntimeError("UART reader did not stop")

    def run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    with serial.Serial(self.port, 115200, timeout=0.1, exclusive=True) as ser:
                        if sys.platform.startswith("linux"):
                            fcntl.ioctl(ser.fileno(), termios.TIOCEXCL)
                        self.decoder = Decoder()
                        ser.reset_input_buffer()
                        self.serial = ser
                        LOG.info("HH_06.03 UART connected: %s at 115200", self.port)
                        while not self.stop_event.is_set():
                            chunk = ser.read(max(1, 6 - len(self.decoder.buffer)))
                            now = time.monotonic()
                            for frame in self.decoder.feed(chunk):
                                with self.lock:
                                    event = self.meter.consume(frame, now)
                                if event is not None:
                                    event.update(
                                        rejected_frames=self.decoder.rejected,
                                        discarded_bytes=self.decoder.discarded_bytes,
                                    )
                                    self.publish(event)
                except (serial.SerialException, OSError) as error:
                    LOG.warning("HH_06.03 UART disconnected: %s", error)
                    with self.lock:
                        self.meter.disconnected(time.monotonic())
                    self.stop_event.wait(1)
                finally:
                    self.serial = None
        except BaseException as error:
            self.fatal = error
            LOG.exception("HH_06.03 acquisition failed")
