"""Touch navigation and explicitly confirmed, normal systemd poweroff."""

import logging
import os
import subprocess
import sys

POWER_BOX = (264, 200, 312, 239)
CANCEL_BOX = (16, 144, 148, 194)
CONFIRM_BOX = (172, 144, 304, 194)


def inside(point, box):
    x, y = point
    left, top, right, bottom = box
    return left <= x <= right and top <= y <= bottom


def request_shutdown():
    if not sys.platform.startswith("linux") or not os.path.isdir("/run/systemd/system"):
        raise OSError("shutdown requires Linux with systemd")
    # Queue normal shutdown. Never force, invoke a shell, or prompt for credentials.
    subprocess.run(
        ["/usr/bin/systemctl", "--no-block", "--no-ask-password", "poweroff"],
        check=True,
        timeout=3,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


class Controls:
    def __init__(self):
        self.detail = False
        self.state = "normal"
        self.opened = 0
        self.last = -1.0

    def tick(self, now):
        if self.state == "confirm" and now - self.opened >= 15:
            self.state = "normal"

    def tap(self, point, now):
        self.tick(now)
        if now - self.last < 0.4:
            return
        self.last = now
        if self.state == "normal":
            if self.detail and inside(point, POWER_BOX):
                self.state = "confirm"
                self.opened = now
            else:
                self.detail = not self.detail
        elif self.state == "confirm":
            if inside(point, CANCEL_BOX):
                self.state = "normal"
            elif now - self.opened >= 0.75 and inside(point, CONFIRM_BOX):
                self.state = "pending"
        elif self.state == "failed" and inside(point, CANCEL_BOX):
            self.state = "normal"

    def dispatch(self, request=request_shutdown):
        # Call only AFTER the shutting-down screen has reached the framebuffer.
        if self.state != "pending":
            return
        self.state = "shutting_down"
        try:
            request()
        except (OSError, subprocess.SubprocessError):
            logging.getLogger("pinoise").exception("Shutdown request failed")
            self.state = "failed"
