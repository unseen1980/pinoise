"""320x240 framebuffer presentation; animation never changes measurements."""

import math
import os
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageChops
from .controls import POWER_BOX, CANCEL_BOX, CONFIRM_BOX

BG = (12, 16, 24)
FG = (232, 237, 244)
DIM = (139, 151, 170)
BLUE = (146, 196, 255)


def font(size):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


FONTS = {n: font(n) for n in (11, 13, 16, 38, 46)}


def color(value):
    return (240, 86, 74) if value >= 70 else (247, 181, 74) if value >= 55 else (74, 210, 128)


def point(value, radius=93, center=(160, 122)):
    angle = math.radians(160 + 220 * (min(100, max(30, value)) - 30) / 70)
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))


DIAL_RADIUS = 65
DIAL_CENTER = (80, 99)
DASHBOARD_GRAPH = (30, 157, 307, 220)


@lru_cache(maxsize=128)
def glyph(content, size, fill):
    bounds = FONTS[size].getbbox(content)
    left, top, right, bottom = bounds
    tile = Image.new("L", (max(1, right - left), max(1, bottom - top)), 0)
    ImageDraw.Draw(tile).text((-left, -top), content, font=FONTS[size], fill=255)
    return tile, (left, top)


def text(img, xy, content, size, fill):
    tile, offset = glyph(content, size, fill)
    x, y = int(xy[0] + 0.5) + offset[0], int(xy[1] + 0.5) + offset[1]
    img.paste(fill, (x, y, x + tile.width, y + tile.height), tile)


def graph(draw, history, now, span, box, shaded=False):
    x0, y0, x1, y1 = box
    for level in (40, 60, 80):
        y = y1 - (level - 30) / 70 * (y1 - y0)
        draw.line((x0, y, x1, y), fill=(34, 44, 60))
    previous = None
    for t, value in history:
        if t < now - span or t > now:
            continue
        if value is None:
            previous = None
            continue
        x = x0 + max(0, min(1, (t - now + span) / span)) * (x1 - x0)
        y = y1 - max(0, min(1, (value - 30) / 70)) * (y1 - y0)
        if previous and 0 < t - previous[2] < 1.5:
            if shaded:
                draw.polygon(
                    ((previous[0], y1), (previous[0], previous[1]), (x, y), (x, y1)),
                    fill=(19, 37, 43),
                )
            draw.line((previous[0], previous[1], x, y), fill=color(value), width=2)
        previous = (x, y, t)


def history_range(history, now, span):
    values = [v for t, v in history if now - span <= t <= now and v is not None]
    return (min(values), max(values)) if values else (None, None)


@lru_cache(maxsize=1)
def dashboard_background():
    img = Image.new("RGB", (320, 240), BG)
    d = ImageDraw.Draw(img)
    text(img, (12, 5), "PiNoise", 16, FG)
    d.line((12, 28, 308, 28), fill=(34, 44, 60))
    for lo, hi in ((30, 55), (55, 70), (70, 100)):
        points = [point(lo + (hi - lo) * i / 40, DIAL_RADIUS, DIAL_CENTER) for i in range(41)]
        d.line(points, fill=color((lo + hi) / 2), width=6)
    for value in (30, 40, 50, 60, 70, 80, 90, 100):
        d.line((*point(value, 54, DIAL_CENTER), *point(value, 58, DIAL_CENTER)), fill=DIM)
    for value in (40, 60, 80, 100):
        x, y = point(value, 43, DIAL_CENTER)
        content = str(value)
        tile, _ = glyph(content, 11, DIM)
        text(img, (x - tile.width / 2, y - 7), content, 11, DIM)
    text(img, (30, 141), "LAST 90s", 11, DIM)
    for level in (40, 60, 80):
        y = 220 - (level - 30) / 70 * 63
        text(img, (9, y - 7), str(level), 11, DIM)
    text(img, (30, 223), "-90s", 11, DIM)
    text(img, (151, 223), "-45s", 11, DIM)
    text(img, (279, 223), "NOW", 11, DIM)
    return img


def render(snapshot, history, now, needle=None, graph_view=False):
    img = Image.new("RGB", (320, 240), BG) if graph_view else dashboard_background().copy()
    d = ImageDraw.Draw(img)
    value = snapshot.get("slow_db")
    status = snapshot["status"]
    if graph_view:
        text(img, (12, 8), "PiNoise", 16, FG)
        text(img, (202, 10), snapshot.get("display_label", "HH06 · REPORTED"), 11, DIM)
        if snapshot.get("presentation_smoothed") and value is not None:
            raw_status = snapshot.get("raw_status")
            # Never print an out-of-range module value as if it were a measurement.
            raw = (
                "RAW " + raw_status
                if raw_status in ("BELOW RANGE", "ABOVE RANGE")
                else "RAW %.1f" % snapshot["reported_db"]
            )
            text(img, (12, 32), raw, 11, DIM)
        graph(d, history, now, 900, (12, 58, 308, 198))
        text(img, (12, 207), "15 MINUTES", 11, DIM)
        d.rectangle(POWER_BOX, outline=DIM, width=1)
        d.arc((279, 207, 297, 225), -45, 225, fill=FG, width=2)
        d.line((288, 205, 288, 215), fill=FG, width=2)
    else:
        offline = status == "SENSOR OFFLINE"
        badge = "OFFLINE" if offline else "LIVE" if value is not None else "CHECK"
        d.ellipse(
            (241, 12, 246, 17), fill=DIM if offline else color(value) if value is not None else BLUE
        )
        text(img, (253, 6), badge, 11, DIM if offline else FG)
        text(
            img,
            (164, 34),
            "SMOOTHED" if snapshot.get("presentation_smoothed") else "REPORTED",
            11,
            DIM,
        )
        if value is not None:
            tip = point(value if needle is None else needle, 51, DIAL_CENTER)
            d.line((*DIAL_CENTER, *tip), fill=FG, width=3)
            d.ellipse((75, 94, 85, 104), fill=FG)
        label = "--" if value is None else "%.1f" % value
        text(img, (161, 48), label, 38, FG if value is None else color(value))
        text(img, (165, 94), "dBA est.", 11, DIM)
        low, high = history_range(history, now, 90) if value is not None else (None, None)
        text(img, (12, 123), "MIN --" if low is None else "MIN %.1f" % low, 13, DIM)
        text(img, (224, 123), "MAX --" if high is None else "MAX %.1f" % high, 13, BLUE)
        graph(d, history, now, 90, DASHBOARD_GRAPH, shaded=True)
    status_text = (
        status
        if status != "OK"
        else ("QUIET" if value < 55 else "MODERATE" if value < 70 else "LOUD")
    )
    if graph_view:
        if value is None:
            text(img, (12, 32), status_text, 13, FG)
    elif value is not None:
        text(img, (225, 94), status_text, 11, color(value))
    else:
        # Long fault strings fit below the header without colliding with the dial.
        text(img, (12, 31), status_text, 11, BLUE)
    return img


def render_controls(state):
    img = Image.new("RGB", (320, 240), BG)
    d = ImageDraw.Draw(img)
    text(img, (16, 12), "PiNoise", 16, FG)
    d.line((16, 40, 304, 40), fill=(34, 44, 60))
    if state == "confirm":
        text(img, (16, 64), "Shut down Raspberry Pi?", 16, FG)
        text(img, (16, 96), "Stops the monitor and the system.", 13, DIM)
        text(img, (16, 116), "Keep power connected while it stops.", 13, DIM)
        d.rectangle(CANCEL_BOX, outline=DIM, width=1)
        d.rectangle(CONFIRM_BOX, fill=(123, 43, 39))
        text(img, (53, 160), "Cancel", 16, FG)
        text(img, (194, 160), "Shut down", 16, FG)
        text(img, (16, 210), "Closes automatically after 15 seconds.", 11, DIM)
    elif state == "failed":
        text(img, (16, 64), "Shutdown request failed", 16, FG)
        text(img, (16, 96), "The monitor is still running.", 13, DIM)
        text(img, (16, 116), "Check permissions and service logs.", 13, DIM)
        d.rectangle(CANCEL_BOX, outline=DIM, width=1)
        text(img, (58, 160), "Back", 16, FG)
    else:
        text(img, (16, 72), "Shutting down...", 16, FG)
        text(img, (16, 108), "Keep power connected.", 13, DIM)
        text(img, (16, 134), "Wait for system shutdown to finish.", 13, DIM)
    return img


def pack_rgb565(img):
    # Pillow's byte lookup/merge operations run in native code on ARMv6.
    red, green, blue = img.split()
    high = ImageChops.add(
        red.point([v & 248 for v in range(256)]), green.point([v >> 5 for v in range(256)])
    )
    low = ImageChops.add(
        green.point([(v & 28) << 3 for v in range(256)]), blue.point([v >> 3 for v in range(256)])
    )
    return Image.merge("LA", (low, high)).tobytes()


class Framebuffer:
    def __init__(self, path):
        base = "/sys/class/graphics/" + os.path.basename(path)
        with open(base + "/virtual_size") as f:
            dimensions = f.read().strip()
        with open(base + "/bits_per_pixel") as f:
            depth = int(f.read())
        with open(base + "/stride") as f:
            self.stride = int(f.read())
        if dimensions != "320,240" or depth != 16 or self.stride < 640:
            raise RuntimeError("expected 320x240 RGB565 framebuffer")
        self.file = open(path, "r+b", buffering=0)

    def show(self, img):
        packed = pack_rgb565(img)
        if self.stride != 640:
            pad = bytes(self.stride - 640)
            packed = b"".join(packed[row * 640 : (row + 1) * 640] + pad for row in range(240))
        data = memoryview(packed)
        self.file.seek(0)
        while data:
            n = self.file.write(data)
            if not n:
                raise OSError("framebuffer write made no progress")
            data = data[n:]

    def close(self):
        self.file.close()
