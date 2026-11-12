"""Advisory lighting measurements and bounded DirectShow exposure assistance.

No pixel correction or authentication decisions. Driver calls belong exclusively
to the capture thread; unsupported controls leave the ordinary camera usable.
"""
import math
from collections import deque

import cv2
import numpy as np


MESSAGES = {
    "low": "Low light: add a light in front of you.",
    "bright": "Too bright: move away from direct glare.",
    "uneven": "Uneven light: avoid a bright light behind or beside you.",
    "good": "Lighting looks usable; keep both eyes clearly visible.",
    "unknown": "Waiting for a lighting measurement.",
}


def measure_lighting(image, scope="scene"):
    # A tiny sample is enough for guidance; never mutate the inference image.
    gray = cv2.cvtColor(cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    halves = (float(gray[:, :32].mean()), float(gray[:, 32:].mean()))
    clipped = float(np.mean(gray >= 245))
    state = ("low" if mean < 55 else "bright" if mean > 210 or clipped > .35
             else "uneven" if abs(halves[0] - halves[1]) > 65 else "good")
    return {"state": state, "scope": scope, "brightness": round(mean, 1), "message": MESSAGES[state]}


class ExposureTuner:
    # DirectShow uses log2(seconds). -6 is 15.6 ms, not an arbitrary
    # cross-backend exposure value. Never force FPS or use positive exposure.
    MAX_EXPOSURE = -6
    MIN_HZ = 24
    BASELINE_SECONDS = .8
    SETTLE_SECONDS = .45

    def __init__(self, device, backend, enabled, now):
        self.device = device
        self.state = "off" if not enabled else "unsupported"
        self.original = None
        self.changed = False
        self.ready = True
        self.started = now
        self.times = []
        self.monitor_times = deque(maxlen=16)
        self.low_samples = 0
        self.last = None
        self.settling_until = 0
        if not enabled or backend != "DirectShow":
            return
        try:
            exposure = float(device.get(cv2.CAP_PROP_EXPOSURE))
            auto = float(device.get(cv2.CAP_PROP_AUTO_EXPOSURE))
            if (not math.isfinite(exposure) or exposure != round(exposure) or not -13 <= exposure <= -1
                    or auto not in (0., 1.)):
                return
            self.original = (exposure, auto)
            self.state = "checking"
            self.ready = False
        except Exception:
            pass

    def restore(self):
        if not self.changed:
            return True
        # Try both properties even if the first fails; auto mode is restored last.
        ok = True
        for prop, value in ((cv2.CAP_PROP_EXPOSURE, self.original[0]),
                            (cv2.CAP_PROP_AUTO_EXPOSURE, self.original[1])):
            try:
                accepted = bool(self.device.set(prop, value))
                readback = float(self.device.get(prop))
                ok = accepted and math.isfinite(readback) and abs(readback - value) < .1 and ok
            except Exception:
                ok = False
        if ok:
            self.changed = False
        else:
            self.state = "restore_failed"
        return ok

    def update(self, now, lighting):
        """Return True whenever controls change, so old evidence is discarded."""
        gap = now - self.last if self.last is not None else 0
        self.last = now
        self.monitor_times.append(now)
        if self.state == "tuned":
            measured_hz = ((len(self.monitor_times) - 1) / (now - self.monitor_times[0])
                           if len(self.monitor_times) >= 8 and now > self.monitor_times[0] else self.MIN_HZ)
            if gap > .08 or measured_hz < self.MIN_HZ or lighting["state"] == "bright":
                restored = self.restore()
                if restored:
                    self.state = "limited"
                self.settling_until = now + .25
                return True
            return False
        if self.ready:
            return False
        self.times.append(now)
        self.low_samples += lighting["state"] == "low"
        elapsed = now - self.started
        wait = self.SETTLE_SECONDS if self.state == "settling" else self.BASELINE_SECONDS
        if elapsed < wait:
            return False
        hz = (len(self.times) - 1) / (self.times[-1] - self.times[0]) if len(self.times) > 1 and self.times[-1] > self.times[0] else 0
        if self.state == "settling":
            self.ready = True
            if hz < self.MIN_HZ or gap > .08 or lighting["state"] == "bright":
                restored = self.restore()
                if restored:
                    self.state = "limited"
                self.settling_until = now + .25
                return True
            self.state = "tuned"
            return False
        self.ready = True
        if self.low_samples < len(self.times) * .75:
            self.state = "not_needed"
            return False
        target = min(self.original[0] + 2, self.MAX_EXPOSURE)
        if hz < self.MIN_HZ or target <= self.original[0]:
            self.state = "limited"
            return False
        try:
            # A driver can mutate a property even when it reports failure.
            self.changed = True
            if not self.device.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0):
                raise ValueError()
            readback = float(self.device.get(cv2.CAP_PROP_AUTO_EXPOSURE))
            if not math.isfinite(readback) or abs(readback) > .1:
                raise ValueError()
            if not self.device.set(cv2.CAP_PROP_EXPOSURE, target):
                raise ValueError()
            readback = float(self.device.get(cv2.CAP_PROP_EXPOSURE))
            if not math.isfinite(readback) or abs(readback - target) > .1:
                raise ValueError()
            self.state = "settling"
            self.ready = False
            self.started = now
            self.times.clear()
            self.settling_until = now + self.SETTLE_SECONDS
        except Exception:
            if self.restore():
                self.state = "unsupported"
            self.settling_until = now + .25
        return True
