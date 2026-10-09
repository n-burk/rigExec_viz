"""Fire activity: which nodes lit up, and how far each has faded.

Pure data, no Qt: the overlay widget renders whatever this reports.
Time comes from the caller (``time.monotonic`` in the widget, scripted
clocks in tests), so decay is deterministic under test.
"""

from __future__ import annotations

import math


class ActivityModel:
    """Exponential-decay activity per key (node id, link id, ...)."""

    def __init__(self, tau=0.45, floor=0.01):
        self.tau = float(tau)
        self.floor = float(floor)
        self._last_fire = {}

    @property
    def fade_seconds(self):
        """How long a fire stays visible (to ~1% brightness)."""
        return -self.tau * math.log(self.floor)

    def fire(self, keys, now):
        """Light ``keys`` at their brightest at time ``now``."""
        for key in keys:
            self._last_fire[key] = now

    def value(self, key, now):
        """Current brightness of ``key`` in [0, 1]."""
        fired = self._last_fire.get(key)
        if fired is None:
            return 0.0
        return math.exp(-max(0.0, now - fired) / self.tau)

    def live(self, now):
        """``{key: brightness}`` for everything still above the floor."""
        out = {}
        for key, fired in list(self._last_fire.items()):
            value = math.exp(-max(0.0, now - fired) / self.tau)
            if value <= self.floor:
                del self._last_fire[key]
            else:
                out[key] = value
        return out

    def clear(self):
        self._last_fire.clear()
