"""Synthetic component benchmark. No models, camera, or stored user profile."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter
import tracemalloc

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.viso.enrollment import ENROLLMENT_VERSION, STEPS, TARGETS
from backend.viso.recognition import MODEL_ID, ProfileMatcher, normalized
from backend.viso.storage import dpapi


def previous_normalized(vector):
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(vector).all() or norm < 1e-8:
        raise ValueError("Invalid face embedding.")
    return vector / norm


def previous_similarity(first, second):
    return float(np.clip(np.dot(previous_normalized(first), previous_normalized(second)), -1, 1))


def previous(probe, profile):
    # 0.7.1's per-vector implementation, applied to the same view count.
    score = previous_similarity(probe, np.asarray(profile["embedding"]))
    scores = sorted(previous_similarity(probe, np.asarray(view)) for view in profile["templates"])
    return max(score, scores[-2])


def measure(function, probe, iterations):
    for _ in range(100):
        function(probe)
    timings = []
    for _ in range(5):
        start = perf_counter()
        for _ in range(iterations):
            function(probe)
        timings.append((perf_counter() - start) * 1e6 / iterations)
    tracemalloc.start()
    for _ in range(100):
        function(probe)
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"median_us": round(statistics.median(timings), 2),
            "runs_us": [round(value, 2) for value in timings],
            "traced_retained_bytes_100_calls": retained,
            "traced_peak_bytes_100_calls": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--output", type=Path, default=Path("test-results/matcher.json"))
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    rng = np.random.default_rng(20261111)
    probe = normalized(rng.normal(size=128))
    views = [normalized(probe + rng.normal(0, .025, 128)).tolist() for _ in STEPS]
    circular = {"id": "synthetic-only", "name": "Synthetic matcher benchmark", "model_id": MODEL_ID,
                "source": "camera", "guided": True, "enrollment_version": ENROLLMENT_VERSION,
                "samples": len(STEPS), "observations": 3 * len(STEPS), "embedding": normalized(np.mean(views, axis=0)).tolist(),
                "templates": views, "template_groups": [step[0] for step in STEPS],
                "poses": [{"step": step[0], "yaw": TARGETS[step[0]][0], "pitch": TARGETS[step[0]][1], "observations": 3} for step in STEPS]}
    legacy = {"embedding": circular["embedding"], "templates": views[:5]}
    results = []
    for label, profile in (("legacy-five-view", legacy), ("circular-seventeen-view", circular)):
        matcher = ProfileMatcher(profile)
        old = measure(lambda value: previous(value, profile), probe, args.iterations)
        new = measure(matcher.score, probe, args.iterations)
        results.append({"case": label, "previous": old, "compiled": new,
                        "speedup": round(old["median_us"] / new["median_us"], 2),
                        "compiled_array_bytes": matcher.centroid.nbytes + matcher.views.nbytes + (0 if matcher.group_starts is None else matcher.group_starts.nbytes)})
    # Legacy scores must match within float32 rounding. Circular scoring has an
    # intentionally stricter distinct-pose rule, not identical semantics.
    error = 0.0
    matcher = ProfileMatcher(legacy)
    for _ in range(100):
        candidate = normalized(rng.normal(size=128))
        error = max(error, abs(previous(candidate, legacy) - matcher.score(candidate)))
    assert error < 1e-6
    payload = json.dumps(circular, allow_nan=False).encode()
    assert len(payload) < 65536
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "numpy": np.__version__, "iterations_per_run": args.iterations, "runs": 5, "cases": results,
              "legacy_max_score_error": error, "synthetic_profile_json_bytes": len(payload),
              "synthetic_dpapi_bytes": len(dpapi(payload)) if sys.platform == "win32" else None,
              "scope": "Matcher-only synthetic benchmark; tracemalloc peaks are not total allocation traffic or process working set. No biometric accuracy or end-to-end scan latency measurement."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
