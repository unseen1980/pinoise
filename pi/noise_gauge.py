#!/usr/bin/env python3
"""HH_06.03 sound-level dashboard and read-only measurement stream."""

import argparse
import logging
import math
import os
import signal
import threading
import time
from pinoise.hh0603 import Acquisition, Meter
from pinoise.runtime import Broker
from pinoise.presentation import SmoothedView
from pinoise.controls import Controls
from pinoise.touch import add_arguments, from_arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.getenv("NOISE_SERIAL", "/dev/ttyAMA0"))
    parser.add_argument("--framebuffer", default=os.getenv("NOISE_FB", "/dev/fb1"))
    parser.add_argument("--socket", default="/run/pinoise/measurements.sock")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--duration", type=float, default=0)
    add_arguments(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    broker = Broker(args.socket, {"source": "hh0603"})
    meter = Meter()
    source = Acquisition(args.serial, meter, broker.publish)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    fb = touch = None
    try:
        if not args.headless:
            from pinoise.display import Framebuffer, render, render_controls

            fb = Framebuffer(args.framebuffer)
            touch = from_arguments(args)
        broker.start()
        source.start()
        started = last_frame = last_health = time.monotonic()
        needle = None
        controls = Controls()
        presentation = SmoothedView()
        while not stop.is_set():
            now = time.monotonic()
            dt = now - last_frame
            last_frame = now
            if source.fatal is not None:
                raise RuntimeError("acquisition thread failed") from source.fatal
            snap = source.snapshot()
            shown, shown_history = presentation.update(snap, now)
            target = shown.get("slow_db")
            if target is None:
                needle = None
            elif needle is None:
                needle = target
            else:
                needle += (target - needle) * (-math.expm1(-dt / 0.12))
            if fb:
                controls.tick(now)
                for point in touch.taps(now):
                    controls.tap(point, now)
                if controls.state == "normal":
                    fb.show(render(shown, shown_history, now, needle, controls.detail))
                else:
                    fb.show(render_controls(controls.state))
                controls.dispatch()
            if now - last_health >= 5:
                broker.publish(dict(snap, kind="health", mono=now))
                last_health = now
            if args.duration and now - started >= args.duration:
                break
            stop.wait(max(0.0, 0.25 - (time.monotonic() - now)))
    finally:
        close_all(
            (
                source.close if source.ident is not None else None,
                broker.close,
                fb.close if fb else None,
                touch.close if touch else None,
            )
        )
    return 0


def close_all(closers):
    """Run every cleanup step, then re-raise the first failure."""
    first = None
    for close in closers:
        if close is None:
            continue
        try:
            close()
        except Exception as error:
            logging.getLogger("pinoise").exception("Cleanup step failed")
            if first is None:
                first = error
    if first is not None:
        raise first


if __name__ == "__main__":
    raise SystemExit(main())
