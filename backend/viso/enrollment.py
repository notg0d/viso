"""Two server-owned circular sweeps of distinct, open-eye, same-person views."""

from dataclasses import dataclass, field
from math import atan2, degrees
from time import monotonic

import numpy as np

from .recognition import Observation, normalized, similarity
from .attention import EyeCalibration, apply_eye_state

ENROLLMENT_VERSION = "circular-v1"
CIRCUIT = (
    ("left", "Turn gently to your left", "Start the circle to your left, keeping both eyes visible."),
    ("up_left", "Continue left and slightly up", "Move gently around the circle. Keep your eyes on the camera."),
    ("up", "Lift your chin slightly", "Continue across the top of the circle, with a small chin lift."),
    ("up_right", "Continue slightly up and right", "Keep moving gently around the circle toward your right."),
    ("right", "Turn gently to your right", "Keep both eyes visible as you pass the right side."),
    ("down_right", "Continue right and slightly down", "Lower your chin a little as you continue the circle."),
    ("down", "Lower your chin slightly", "Continue across the bottom of the circle. Use small movements."),
    ("down_left", "Continue slightly down and left", "Complete this circle toward your left. Keep both eyes visible."),
)
STEPS = (
    ("center", "Look straight at the camera", "Keep your head upright and both eyes open."),
) + CIRCUIT * 2

TARGETS = {"center": (0, 0, 10, 18), "left": (14, 0, 8, 6), "right": (-14, 0, 8, 6),
           "up": (0, -10, 8, 6), "down": (0, 10, 8, 6),
           "up_left": (10, -7, 7, 5), "up_right": (-10, -7, 7, 5),
           "down_left": (10, 7, 7, 5), "down_right": (-10, 7, 7, 5)}
RECENTER = (0, 0, 9, 9)
MAX_ROLL = 18


def validate_circular_profile(profile: dict) -> None:
    """Bound the new format and require the complete, ordered pose coverage."""
    expected = [step[0] for step in STEPS]
    poses = profile.get("poses")
    if (profile.get("enrollment_version") != ENROLLMENT_VERSION
            or type(profile.get("samples")) is not int or profile["samples"] != len(STEPS)
            or profile.get("template_groups") != expected
            or not isinstance(poses, list) or len(poses) != len(STEPS)):
        raise ValueError("Complete both circular camera enrollment passes first.")
    for step, pose in zip(expected, poses):
        if (not isinstance(pose, dict) or pose.get("step") != step
                or type(pose.get("observations")) is not int or not 3 <= pose["observations"] <= 12
                or any(isinstance(pose.get(key), bool) or not isinstance(pose.get(key), (int, float))
                       or not np.isfinite(pose[key]) for key in ("yaw", "pitch"))):
            raise ValueError("Invalid circular enrollment coverage.")
    if type(profile.get("observations")) is not int or profile["observations"] != sum(pose["observations"] for pose in poses):
        raise ValueError("Invalid circular enrollment observation count.")


def pose_matches(step: str, yaw: float, pitch: float, roll: float) -> bool:
    if not np.isfinite([yaw, pitch, roll]).all() or abs(roll) > MAX_ROLL:
        return False
    if step not in TARGETS:
        return False
    target_yaw, target_pitch, tolerance_yaw, tolerance_pitch = TARGETS[step]
    if abs(yaw - target_yaw) > tolerance_yaw or abs(pitch - target_pitch) > tolerance_pitch:
        return False
    if step == "center":
        return True
    # Separate eight sectors in normalized pose space. A cardinal view cannot
    # fill its neighboring diagonal merely by holding the same pose longer.
    angle = degrees(atan2(-pitch / 10, yaw / 14))
    target = degrees(atan2(-target_pitch / 10, target_yaw / 14))
    return abs((angle - target + 180) % 360 - 180) <= 24


@dataclass
class Enrollment:
    id: str
    name: str
    started_at: float
    state: str = "capturing"
    message: str = "Face the camera, then make two small, slow circles with your head."
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
            matches = (np.isfinite([yaw, pitch, roll]).all() and abs(yaw) <= RECENTER[2] and abs(pitch) <= RECENTER[3] and abs(roll) <= MAX_ROLL) if self.returning else pose_matches(step, yaw, pitch, roll)
            if not matches:
                self.reset_hold()
                if abs(roll) > MAX_ROLL:
                    self.message = "Keep your head upright; turn instead of tilting sideways."
                elif self.returning:
                    self.message = "Look roughly toward the camera again."
                else:
                    target_yaw, target_pitch, tolerance_yaw, tolerance_pitch = TARGETS[step]
                    if abs(pitch - target_pitch) > tolerance_pitch:
                        self.message = "Lift your chin a little." if pitch > target_pitch else "Lower your chin a little."
                    else:
                        self.message = "Turn a little to your left." if yaw < target_yaw else "Turn a little to your right."
            else:
                if self.held_pose is not None and max(abs(yaw - self.held_pose[0]), abs(pitch - self.held_pose[1]), abs(roll - self.held_pose[2])) > 9:
                    self.reset_hold()
                if self.hold_at is None:
                    self.hold_at, self.held_pose = now, (yaw, pitch, roll)
                self.hold_frames += 1
                self.hold_samples.append((observation.embedding.copy(), (attention.yaw, attention.pitch, attention.roll)))
                self.hold_samples = self.hold_samples[-12:]
                duration = .12 if self.returning else .24
                self.hold_progress = min(1, (now - self.hold_at) / duration)
                self.message = "That's enough. Pause briefly…"
                if self.hold_frames >= (2 if self.returning else 3) and now - self.hold_at >= duration:
                    if self.returning:
                        self.returning = False
                        self.reset_hold()
                        self.message = "Centered. Follow the next direction."
                        return self.public()
                    # Aggregate a stable hold instead of saving its last, possibly
                    # noisy frame. Neutral calibration uses the same robust hold.
                    pose = np.median([item[1] for item in self.hold_samples], axis=0)
                    self.embeddings.append(normalized(np.mean([item[0] for item in self.hold_samples], axis=0)))
                    self.poses.append({"step": step, "yaw": round(float(pose[0]), 1), "pitch": round(float(pose[1]), 1),
                                       "observations": len(self.hold_samples)})
                    if self.baseline is None:
                        self.baseline = (float(pose[0]), float(pose[1]))
                    self.reset_hold()
                    self.message = "View captured. Continue gently around the circle."
                    self.pose_history.clear()
                    self.returning = len(self.embeddings) == 1 + len(CIRCUIT)
                    if len(self.embeddings) == len(STEPS):
                        self.state = "ready"
                        self.returning = False
                        self.message = "Both circles captured. Your face profile is ready."
        return self.public()

    def public(self) -> dict:
        index = len(self.embeddings)
        step = STEPS[min(index, len(STEPS) - 1)]
        target = RECENTER if self.returning else TARGETS[step[0]]
        guidance = {"yaw": round(self.measured_pose[0], 1) if self.measured_pose else None,
                    "pitch": round(self.measured_pose[1], 1) if self.measured_pose else None,
                    "target_yaw": target[0], "target_pitch": target[1],
                    "tolerance_yaw": target[2], "tolerance_pitch": target[3]}
        circuit = min(2, max(1, (max(1, index) - 1) // len(CIRCUIT) + 1))
        circuit_captured = max(0, min(len(CIRCUIT), index - 1 - (circuit - 1) * len(CIRCUIT)))
        if self.returning:
            circuit, circuit_captured = 1, len(CIRCUIT)
        return {"id": self.id, "state": self.state, "captured": index, "total": len(STEPS), "step": step[0],
                "circuit": circuit, "circuits": 2, "circuit_captured": circuit_captured,
                "circuit_total": len(CIRCUIT), "observations": sum(pose["observations"] for pose in self.poses),
                "enrollment_version": ENROLLMENT_VERSION,
                "title": "Return to the center" if self.returning else step[1],
                "instruction": "Face the camera briefly before making the second circle." if self.returning else step[2],
                "message": self.message, "hold_progress": round(self.hold_progress, 2),
                "steps": [item[0] for item in STEPS], "returning": self.returning, "guidance": guidance}
