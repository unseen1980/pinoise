"""Robust trend presentation, not acoustic calibration or IEC time weighting.

A three-reading median suppresses isolated excursions (including genuine short
sounds). A 0.6 s exponential glide in displayed dB makes sustained changes
readable. Raw measurements and telemetry are never modified.

A single valid packet outside the module's specified range is treated like any
other isolated excursion: the displayed trend is held and the raw status is
reported separately. Two or more consecutive out-of-range packets hide the
number, because no value is ever invented outside the specified range.
"""

import collections
import math
import statistics

OUT_OF_RANGE = ("BELOW RANGE", "ABOVE RANGE")
GAP_SECONDS = 1.5
GLIDE_SECONDS = 0.6
HISTORY_STEP = 0.5
MAX_WINDOW = 4


class SmoothedView:
    def __init__(self):
        self.samples = collections.deque(maxlen=3)
        self.history = collections.deque(maxlen=3605)
        self.recent = collections.deque()
        self.received = None
        self.last = None
        self.value = None
        self.target = None
        self.history_at = None
        self.excursions = 0

    def _clear_trend(self, now):
        if self.value is not None:
            self.history.append((now, None))
        self.samples.clear()
        self.recent.clear()
        self.value = None
        self.target = None

    def update(self, snapshot, now):
        shown = dict(snapshot)
        raw = snapshot.get("slow_db")
        status = snapshot.get("status")
        stamp = snapshot.get("received_mono")
        out_of_range = raw is None and status in OUT_OF_RANGE and stamp is not None
        if raw is None and not out_of_range:
            # Offline: there is no current reading to hold.
            self._clear_trend(now)
            self.received = None
            self.last = None
            self.excursions = 0
        else:
            if stamp != self.received:
                if self.received is not None and (
                    stamp - self.received > GAP_SECONDS or stamp < self.received
                ):
                    self._clear_trend(now)
                    self.excursions = 0
                self.received = stamp
                if out_of_range:
                    self.excursions += 1
                else:
                    self.excursions = 0
                    self.samples.append(raw)
                    # Hold startup's first reading until a complete median exists.
                    self.target = (
                        statistics.median(self.samples)
                        if len(self.samples) == 3
                        else self.samples[0]
                    )
            if out_of_range and (self.excursions > 1 or self.value is None):
                self._clear_trend(now)
            else:
                if out_of_range:
                    shown["status"] = "OK"
                if self.value is None:
                    self.value = self.target
                else:
                    dt = max(0, now - self.last)
                    self.value += (self.target - self.value) * (-math.expm1(-dt / GLIDE_SECONDS))
                self.recent.append((now, self.value))
                if self.history_at is None or now - self.history_at >= HISTORY_STEP:
                    self.history.append((now, self.value))
                    self.history_at = now
            self.last = now
        while self.recent and self.recent[0][0] < now - MAX_WINDOW:
            self.recent.popleft()
        shown.update(
            slow_db=self.value,
            max_slow_db=max((v for _, v in self.recent), default=None),
            raw_status=status,
            display_label="HH06 SMOOTHED",
            presentation_smoothed=True,
        )
        return shown, list(self.history)
