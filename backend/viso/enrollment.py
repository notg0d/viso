"""Server-owned pose sequence; capture only stable, open-eye, same-person samples."""

from dataclasses import dataclass, field
from time import monotonic

import numpy as np

from .recognition import Observation, similarity

STEPS = (
    ("center", "Look straight at the camera", "Keep your head upright and both eyes open."),
    ("left", "Turn slightly to your left", "Follow the left arrow. Keep both eyes visible."),
    ("right", "Turn slightly to your right", "Follow the right arrow. Keep both eyes visible."),
    ("up", "Lift your chin slightly", "Look a little upward, keeping your eyes open."),
    ("down", "Lower your chin slightly", "Look a little downward, keeping your eyes open."),
)


def pose_matches(step: str, yaw: float, pitch: float, roll: float) -> bool:
    if not np.isfinite([yaw, pitch, roll]).all() or abs(roll) > 12:
        return False
    if step == "center":
        return abs(yaw) <= 10 and abs(pitch) <= 18
    if step in ("left", "right"):
        directed = yaw if step == "left" else -yaw
        return 12 <= directed <= 28 and abs(pitch) <= 10
    if step in ("up", "down"):
        directed = -pitch if step == "up" else pitch
        return 10 <= directed <= 23 and abs(yaw) <= 10
    return False


@dataclass
class Enrollment:
    id: str
    name: str
    started_at: float
    state: str = "capturing"
    message: str = "Follow the directions. Each angle is captured automatically."
    embeddings: list = field(default_factory=list)
    poses: list = field(default_factory=list)
    baseline: tuple | None = None
    hold_at: float | None = None
    hold_frames: int = 0
    last_frame_at: float | None = None
    held_pose: tuple | None = None
    hold_progress: float = 0

    def reset_hold(self):
        self.hold_at = self.held_pose = None
        self.hold_frames = 0
        self.hold_progress = 0

    def expire(self, now: float) -> bool:
        if now - self.started_at > 90:
            self.state = "expired"
            self.message = "Enrollment timed out. Start again when you are ready."
            self.embeddings.clear()
            self.poses.clear()
            self.reset_hold()
        return self.state == "expired"

    def observe(self, observation: Observation, now: float | None = None) -> dict:
        now = monotonic() if now is None else now
        if self.expire(now) or self.state != "capturing":
            return self.public()
        if self.last_frame_at is not None and (now <= self.last_frame_at or now - self.last_frame_at > 1):
            self.reset_hold()
        if self.last_frame_at is not None and now - self.last_frame_at < .06:
            return self.public()
        self.last_frame_at = now
        attention = observation.attention
        if observation.embedding is None or observation.face_count != 1:
            self.reset_hold()
            self.message = observation.message
        elif attention is None or attention.eyes != "open" or any(value is None for value in (attention.yaw, attention.pitch, attention.roll)):
            self.reset_hold()
            self.message = "Keep both eyes open and clearly visible."
        elif any(similarity(observation.embedding, other) < .50 for other in self.embeddings):
            self.reset_hold()
            self.message = "This face does not match the earlier samples. Return to the same person."
        else:
            yaw, pitch, roll = attention.yaw, attention.pitch, attention.roll
            if self.baseline:
                yaw, pitch = yaw - self.baseline[0], pitch - self.baseline[1]
            step = STEPS[len(self.embeddings)][0]
            if not pose_matches(step, yaw, pitch, roll):
                self.reset_hold()
                self.message = "Follow the arrow with a small head movement; keep your head upright."
            else:
                if self.held_pose is not None and max(abs(yaw - self.held_pose[0]), abs(pitch - self.held_pose[1]), abs(roll - self.held_pose[2])) > 4:
                    self.reset_hold()
                if self.hold_at is None:
                    self.hold_at, self.held_pose = now, (yaw, pitch, roll)
                self.hold_frames += 1
                self.hold_progress = min(1, (now - self.hold_at) / .45)
                self.message = "Perfect. Hold this position…"
                if self.hold_frames >= 3 and now - self.hold_at >= .45:
                    self.embeddings.append(observation.embedding.copy())
                    self.poses.append({"step": step, "yaw": round(attention.yaw, 1), "pitch": round(attention.pitch, 1)})
                    if self.baseline is None:
                        self.baseline = (attention.yaw, attention.pitch)
                    self.reset_hold()
                    self.message = "Angle captured. Follow the next direction."
                    if len(self.embeddings) == len(STEPS):
                        self.state = "ready"
                        self.message = "All five angles captured."
        return self.public()

    def public(self) -> dict:
        index = len(self.embeddings)
        step = STEPS[min(index, len(STEPS) - 1)]
        return {"id": self.id, "state": self.state, "captured": index, "total": len(STEPS), "step": step[0], "title": step[1], "instruction": step[2], "message": self.message, "hold_progress": round(self.hold_progress, 2), "steps": [item[0] for item in STEPS]}
