"""Linux single-touch evdev input, with explicit screen mapping and tap validation.

Run as a module to inspect coordinates without invoking any power controls.
"""

import argparse
import fcntl
import glob
import logging
import os
import select
import struct
import time

EVENT = struct.Struct("@llHHi")
ABSINFO = struct.Struct("=iiiiii")
LOG = logging.getLogger("pinoise")


class Mapping:
    def __init__(self, bounds, rotation=0, invert_x=False, invert_y=False):
        self.x0, self.x1, self.y0, self.y1 = bounds
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("invalid touch bounds")
        if rotation not in (0, 90, 180, 270):
            raise ValueError("invalid touch rotation")
        self.rotation = rotation
        self.invert_x = invert_x
        self.invert_y = invert_y

    def point(self, x, y):
        if x is None or y is None:
            return None
        if not (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1):
            return None
        x = (x - self.x0) / (self.x1 - self.x0)
        y = (y - self.y0) / (self.y1 - self.y0)
        if self.invert_x:
            x = 1 - x
        if self.invert_y:
            y = 1 - y
        if self.rotation == 90:
            x, y = 1 - y, x
        elif self.rotation == 180:
            x, y = 1 - x, 1 - y
        elif self.rotation == 270:
            x, y = y, 1 - x
        return round(x * 319), round(y * 239)


class TouchStream:
    def __init__(self, mapping):
        self.mapping = mapping
        self.buffer = bytearray()
        self.x = self.y = None
        self.down = False
        self.released = False
        self.start = None
        self.invalid = False
        self.last = -1.0
        self.dropped = False
        self.wait_release = False

    def feed(self, data, now):
        self.buffer.extend(data)
        taps = []
        while len(self.buffer) >= EVENT.size:
            _, _, kind, code, value = EVENT.unpack_from(self.buffer)
            del self.buffer[: EVENT.size]
            if kind == 0 and code == 3:  # SYN_DROPPED: never trust a partial gesture.
                self.dropped = True
                self.wait_release = True
                self.down = False
                self.released = False
                self.start = None
                self.x = self.y = None
                continue
            if self.dropped:
                if kind == 0 and code == 0:
                    self.dropped = False
                continue
            if self.wait_release:
                if kind == 1 and code == 330 and value == 0:
                    self.wait_release = False
                continue
            if kind == 3:
                if code == 0:
                    self.x = value
                elif code == 1:
                    self.y = value
            elif kind == 1 and code == 330:
                if value == 1 and not self.down:
                    self.down = True
                    self.start = None
                    self.invalid = False
                elif value == 0 and self.down:
                    self.down = False
                    self.released = True
            elif kind == 0 and code == 0:
                point = self.mapping.point(self.x, self.y)
                if self.down or self.released:
                    if point is None:
                        self.invalid = True
                    elif self.start is None:
                        self.start = point
                    elif max(abs(point[i] - self.start[i]) for i in (0, 1)) > 18:
                        self.invalid = True
                if self.released:
                    if not self.invalid and point is not None and now - self.last >= 0.4:
                        taps.append(point)
                        self.last = now
                    self.released = False
                    self.start = None
        return taps


def abs_bounds(fd, axis):
    # EVIOCGABS(axis): Linux ARM/x86 generic ioctl layout, struct input_absinfo.
    request = 0x80000000 | (ABSINFO.size << 16) | (ord("E") << 8) | (0x40 + axis)
    _, minimum, maximum, _, _, _ = ABSINFO.unpack(fcntl.ioctl(fd, request, bytes(ABSINFO.size)))
    return minimum, maximum


class Touch:
    def __init__(self, device=None, rotation=0, bounds=None, invert_x=False, invert_y=False):
        self.fd = None
        self.stream = None
        self.path = None
        for path in ([device] if device else sorted(glob.glob("/dev/input/event*"))):
            fd = None
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                axes = (*abs_bounds(fd, 0), *abs_bounds(fd, 1))
                # Require BTN_TOUCH as well as ABS_X/Y; ignore mice and keyboards.
                size = 64
                request = 0x80000000 | (size << 16) | (ord("E") << 8) | 0x21
                keys = fcntl.ioctl(fd, request, bytes(size))
                if not keys[330 // 8] & (1 << (330 % 8)):
                    raise OSError("not a single-touch device")
                mapping = Mapping(
                    bounds if bounds is not None else axes, rotation, invert_x, invert_y
                )
                self.stream = TouchStream(mapping)
                self.fd = fd
                self.path = path
                LOG.info("Touch input %s: bounds=%s rotation=%s", path, bounds or axes, rotation)
                break
            except (OSError, ValueError) as error:
                if fd is not None:
                    os.close(fd)
                if device:
                    LOG.warning("Touch unavailable: %s", error)
        if self.fd is None:
            LOG.warning("No compatible touch input; dashboard remains read-only")

    def taps(self, now):
        if self.fd is None:
            return []
        taps = []
        try:
            # Drain a bounded batch; never let noisy input starve the gauge.
            for _ in range(16):
                ready, _, _ = select.select([self.fd], [], [], 0)
                if not ready:
                    break
                data = os.read(self.fd, EVENT.size * 64)
                if not data:
                    raise OSError("touch input disconnected")
                taps.extend(self.stream.feed(data, now))
        except BlockingIOError:
            pass
        except OSError as error:
            LOG.warning("Touch disabled: %s", error)
            self.close()
        return taps[:1]

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def add_arguments(parser):
    parser.add_argument(
        "--touch-backend",
        choices=("evdev", "stmpe610"),
        default="evdev",
        help="use stmpe610 for a polled SPI0 CS1 touchscreen without an input driver",
    )
    parser.add_argument(
        "--touch-device", default=None, help="evdev path; default: first compatible touchscreen"
    )
    parser.add_argument(
        "--touch-rotation",
        type=int,
        choices=(0, 90, 180, 270),
        default=0,
        help="clockwise rotation after raw-axis inversion",
    )
    parser.add_argument(
        "--touch-bounds",
        type=int,
        nargs=4,
        metavar=("XMIN", "XMAX", "YMIN", "YMAX"),
        help="override kernel ABS_X/Y ranges",
    )
    parser.add_argument("--touch-invert-x", action="store_true")
    parser.add_argument("--touch-invert-y", action="store_true")


def from_arguments(args):
    if args.touch_backend == "stmpe610":
        from .stmpe610 import STMPE610

        return STMPE610(
            args.touch_bounds, args.touch_rotation, args.touch_invert_x, args.touch_invert_y
        )
    return Touch(
        args.touch_device,
        args.touch_rotation,
        args.touch_bounds,
        args.touch_invert_x,
        args.touch_invert_y,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Print released touch coordinates; never powers off."
    )
    add_arguments(parser)
    parser.add_argument("--duration", type=float, default=30)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("duration must be positive")
    logging.basicConfig(level=logging.INFO)
    touch = from_arguments(args)
    try:
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            for point in touch.taps(time.monotonic()):
                print("%d %d" % point, flush=True)
            time.sleep(0.05)
    finally:
        touch.close()


if __name__ == "__main__":
    main()
