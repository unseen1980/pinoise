#!/usr/bin/env python3
"""Read the live production stream; never opens the sensor UART."""

import argparse
import json
import socket
import sys
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--socket", default="/run/pinoise/measurements.sock")
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--clock", action="store_true")
    p.add_argument("--connect-timeout", type=float, default=15)
    a = p.parse_args()
    if a.clock:
        print(json.dumps({"mono": time.monotonic(), "epoch": time.time()}), flush=True)
        return
    if a.duration <= 0:
        p.error("duration must be positive")
    connect_deadline = time.monotonic() + a.connect_timeout
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        while True:
            try:
                client.connect(a.socket)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= connect_deadline:
                    raise
                time.sleep(0.1)
        deadline = time.monotonic() + a.duration
        buffer = b""
        while time.monotonic() < deadline:
            try:
                chunk = client.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("production telemetry disconnected")
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                json.loads(line)
                sys.stdout.buffer.write(line + b"\n")
                sys.stdout.buffer.flush()
            if len(buffer) > 65536:
                raise RuntimeError("oversized telemetry record")


if __name__ == "__main__":
    main()
