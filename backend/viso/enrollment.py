"""Server-owned pose sequence; capture only stable, open-eye, same-person samples."""

from dataclasses import dataclass, field
from time import monotonic

import numpy as np

from .recognition import Observation, normalized, similarity
from .attention import EyeCalibration, apply_eye_state

STEPS = (
    ("center", "Look straight at the camera", "Keep your head upright and both eyes open."),
    ("left", "Turn slightly to your left", "Follow the light to the left. Keep both eyes visible."),
    ("right", "Turn slightly to your right", "Follow the light to the right. Keep both eyes visible."),
    ("up", "Lift your chin slightly", "Follow the light upward. Keep your eyes on the camera."),
    ("down", "Lower your chin slightly", "Follow the light downward. Keep your eyes on the camera."),
)

TARGETS = {"center": (0, 0, 7, 18), "left": (16, 0, 6, 9), "right": (-16, 0, 6, 9),
           "up": (0, -12, 9, 5), "down": (0, 12, 9, 5)}


def pose_matches(step: str, yaw: float, pitch: float, roll: float) -> bool:
    if not np.isfinite([yaw, pitch, roll]).all() or abs(roll) > 12:
        return False
    if step not in TARGETS:
        return False
    target_yaw, target_pitch, tolerance_yaw, tolerance_pitch = TARGETS[step]
    return abs(yaw - target_yaw) <= tolerance_yaw and abs(pitch - target_pitch) <= tolerance_pitch


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
    hold_samples: list = field(default_factory=list)
    returning: bool = False
    measured_pose: tuple | None = None
    pose_history: list = field(default_factory=list)
    calibration: EyeCalibration = field(default_factory=EyeCalibration)
    eye_identity: np.ndarray | None = None

    def reset_hold(self):
        self.hold_at = self.held_pose = None
        self.hold_frames = 0
        self.hold_progress = 0
        self.hold_samples.clear()

    def expire(self, now: float) -> bool:
        if now - self.started_at > 90:
            self.state = "expired"
            self.message = "Enrollment timed out. Start again when you are ready."
            self.embeddings.clear()
            self.poses.clear()
            self.baseline = self.measured_pose = None
            self.pose_history.clear()
            self.calibration = EyeCalibration()
            self.eye_identity = None
            self.reset_hold()
        return self.state == "expired"

    def observe(self, observation: Observation, now: float | None = None) -> dict:
        now = monotonic() if now is None else now
        if self.expire(now) or self.state != "capturing":
            return self.public()
        if self.last_frame_at is not None and (now <= self.last_frame_at or now - self.last_frame_at > 1):
            self.reset_hold()
            self.calibration = EyeCalibration()
            self.eye_identity = None
            self.pose_history.clear()
        if self.last_frame_at is not None and now - self.last_frame_at < .06:
            return self.public()
        self.last_frame_at = now
        attention = observation.attention
        same_person = (observation.embedding is not None and observation.face_count == 1
                       and all(similarity(observation.embedding, other) >= .50
                               for other in self.embeddings + [item[0] for item in self.hold_samples])
                       and (self.eye_identity is None or similarity(observation.embedding, self.eye_identity) >= .50))
        if not same_person or attention is None or attention.eyes == "unknown":
            self.calibration = EyeCalibration()
            self.eye_identity = None
            self.pose_history.clear()
        elif attention is not None:
            state = self.calibration.classify(attention, calibrating=True)
            apply_eye_state(attention, state)
            if self.eye_identity is None and state == "open":
                self.eye_identity = observation.embedding.copy()
        self.measured_pose = None
        if attention is not None and all(value is not None for value in (attention.yaw, attention.pitch, attention.roll)):
            raw_pose = (attention.yaw, attention.pitch, attention.roll)
            if np.isfinite(raw_pose).all():
                self.pose_history = (self.pose_history + [raw_pose])[-3:]
                measured = np.median(self.pose_history, axis=0)
                self.measured_pose = (float(measured[0] - (self.baseline[0] if self.baseline else 0)),
                                      float(measured[1] - (self.baseline[1] if self.baseline else 0)))
        if observation.embedding is None or observation.face_count != 1:
            self.reset_hold()
            self.message = observation.message
        elif not same_person:
            self.reset_hold()
            self.message = "This face does not match the earlier samples. Return to the same person."
        elif attention is None or attention.eyes != "open" or any(value is None for value in (attention.yaw, attention.pitch, attention.roll)):
            self.reset_hold()
            self.message = "Keep your eyes on the camera as you lift your chin." if attention and attention.pitch is not None and attention.pitch < -8 else "Keep both eyes open and clearly visible."
        else:
            yaw, pitch, roll = attention.yaw, attention.pitch, attention.roll
            if self.baseline:
                yaw, pitch = yaw - self.baseline[0], pitch - self.baseline[1]
            step = STEPS[len(self.embeddings)][0]
            matches = (abs(yaw) <= 6 and abs(pitch) <= 6 and abs(roll) <= 12) if self.returning else pose_matches(step, yaw, pitch, roll)
            if not matches:
                self.reset_hold()
                if abs(roll) > 12:
                    self.message = "Keep your head upright; turn instead of tilting sideways."
                elif self.returning:
                    self.message = "Face the camera again. Center your head inside the ring."
                else:
                    target_yaw, target_pitch, tolerance_yaw, tolerance_pitch = TARGETS[step]
                    if abs(pitch - target_pitch) > tolerance_pitch:
                        self.message = "Lift your chin a little." if pitch > target_pitch else "Lower your chin a little."
                    else:
                        self.message = "Turn a little to your left." if yaw < target_yaw else "Turn a little to your right."
            else:
                if self.held_pose is not None and max(abs(yaw - self.held_pose[0]), abs(pitch - self.held_pose[1]), abs(roll - self.held_pose[2])) > 5:
                    self.reset_hold()
                if self.hold_at is None:
                    self.hold_at, self.held_pose = now, (yaw, pitch, roll)
                self.hold_frames += 1
                self.hold_samples.append((observation.embedding.copy(), (attention.yaw, attention.pitch, attention.roll)))
                self.hold_samples = self.hold_samples[-12:]
                duration = .2 if self.returning else .35
                self.hold_progress = min(1, (now - self.hold_at) / duration)
                self.message = "Perfect. Hold this position…"
                if self.hold_frames >= 3 and now - self.hold_at >= duration:
                    if self.returning:
                        self.returning = False
                        self.reset_hold()
                        self.message = "Centered. Follow the next direction."
                        return self.public()
                    # Aggregate a stable hold instead of saving its last, possibly
                    # noisy frame. Neutral calibration uses the same robust hold.
                    pose = np.median([item[1] for item in self.hold_samples], axis=0)
                    self.embeddings.append(normalized(np.mean([item[0] for item in self.hold_samples], axis=0)))
                    self.poses.append({"step": step, "yaw": round(float(pose[0]), 1), "pitch": round(float(pose[1]), 1)})
                    if self.baseline is None:
                        self.baseline = (float(pose[0]), float(pose[1]))
                    self.reset_hold()
                    self.message = "Angle captured. Follow the next direction."
                    self.returning = len(self.embeddings) > 1
                    if len(self.embeddings) == len(STEPS):
                        self.state = "ready"
                        self.returning = False
                        self.message = "All five angles captured."
        return self.public()

    def public(self) -> dict:
        index = len(self.embeddings)
        step = STEPS[min(index, len(STEPS) - 1)]
        target = (0, 0, 6, 6) if self.returning else TARGETS[step[0]]
        guidance = {"yaw": round(self.measured_pose[0], 1) if self.measured_pose else None,
                    "pitch": round(self.measured_pose[1], 1) if self.measured_pose else None,
                    "target_yaw": target[0], "target_pitch": target[1],
                    "tolerance_yaw": target[2], "tolerance_pitch": target[3]}
        return {"id": self.id, "state": self.state, "captured": index, "total": len(STEPS), "step": step[0],
                "title": "Return to the center" if self.returning else step[1],
                "instruction": "Face the camera before the next angle." if self.returning else step[2],
                "message": self.message, "hold_progress": round(self.hold_progress, 2),
                "steps": [item[0] for item in STEPS], "returning": self.returning, "guidance": guidance}
