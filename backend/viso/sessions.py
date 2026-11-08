"""Identity-bound blink challenge for simulated unlocks only."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic


@dataclass
class Attempt:
    id: str
    profile_id: str
    source: str
    threshold: float
    started_at: float
    streak: int = 0
    state: str = "scanning"
    phase: str = "identity"
    message: str = "Look at the camera with both eyes open."
    last_frame_at: float | None = None
    open_at: float | None = None
    prompted_at: float | None = None
    closed_at: float | None = None
    reopened_at: float | None = None

    def reset(self, message: str):
        self.streak = 0
        self.phase = "identity"
        self.open_at = self.prompted_at = self.closed_at = self.reopened_at = None
        self.message = message

    def observe(self, score: float | None, eyes: str = "unknown", now: float | None = None) -> dict:
        now = monotonic() if now is None else now
        if self.state != "scanning":
            return self.public()
        if now - self.started_at > 20:
            self.reset("Test expired. Start again for a fresh blink challenge.")
            self.state = "expired"
            return self.public()
        if self.last_frame_at is not None:
            if now <= self.last_frame_at:
                self.reset("Frame timing changed. Look at the camera again.")
                return self.public()
            if now - self.last_frame_at > 1.0:
                self.reset("Tracking paused. Look at the camera again.")
        self.last_frame_at = now
        if score is None or not isfinite(score) or score < self.threshold:
            self.reset("Keep your enrolled face centered and clearly visible.")
            return self.public()
        if self.source != "camera":
            self.reset("Identity matched. A still image cannot complete the live blink challenge.")
            self.state = "blocked"
            return self.public()
        if eyes == "unknown":
            self.reset("Eyes could not be checked. Keep both eyes visible.")
            return self.public()
        if self.prompted_at is not None and now - self.prompted_at > 6:
            self.reset("Blink challenge timed out. Open both eyes to try again.")

        if self.phase == "identity":
            if eyes != "open":
                self.reset("Open both eyes fully before the blink challenge.")
            else:
                self.open_at = now if self.open_at is None else self.open_at
                self.streak += 1
                self.message = "Face matched. Keep both eyes open…"
                if self.streak >= 3 and now - self.open_at >= .15:
                    self.phase, self.prompted_at = "blink", now
                    self.message = "Blink both eyes now, then reopen them."
        elif self.phase == "blink":
            if eyes == "closed" and now - self.prompted_at >= .15:
                self.phase, self.closed_at = "reopen", now
                self.message = "Blink detected. Reopen both eyes."
        elif self.phase == "reopen":
            if now - self.closed_at > 1.5:
                self.reset("Eyes stayed closed too long. Open them and try a short blink.")
            elif eyes == "open" and now - self.closed_at >= .06:
                self.phase, self.reopened_at = "confirm", now
                self.message = "Keep both eyes open to finish."
        elif self.phase == "confirm":
            if eyes != "open":
                self.reset("Both eyes must stay open to unlock. Please blink again when prompted.")
            elif now - self.reopened_at >= .12:
                self.phase, self.state = "complete", "unlocked"
                self.message = "Face matched, blink verified, both eyes open."
        return self.public()

    def public(self) -> dict:
        return {"id": self.id, "state": self.state, "streak": self.streak, "required": 3, "source": self.source, "threshold": self.threshold, "phase": self.phase, "message": self.message}
