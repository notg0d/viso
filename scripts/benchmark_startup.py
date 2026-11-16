"""Measure isolated model startup and a warm request; never open a camera.

Use --root with an extracted/installed runtime. Results are local diagnostics,
not physical authentication, cold-boot, or LocalSystem performance measurements.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import subprocess
from time import perf_counter


def sample(root: Path) -> dict:
    vector = [1.0] + [0.0] * 127
    request = {"command": "validate", "profile": {
        "id": "synthetic-benchmark", "model_id": "sface-2021dec-yunet-2023mar-v1",
        "source": "camera", "guided": True, "samples": 5,
        "embedding": vector, "templates": [vector] * 5,
    }}
    started = perf_counter()
    process = subprocess.Popen([
        str(root / "runtime" / "python.exe"), "-I", "-B", "-u",
        str(root / "backend" / "viso" / "signin.py"), "--prewarm",
    ], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    # Reads are bounded too: a silent/failed initialization cannot hang a bench.
    reader = ThreadPoolExecutor(max_workers=1)
    try:
        event = json.loads(reader.submit(process.stdout.readline).result(timeout=35))
        if event.get("event") != "ready":
            raise RuntimeError("Model preparation failed: " + str(event.get("event")))
        ready_ms = (perf_counter() - started) * 1000
        warm = perf_counter()
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        event = json.loads(reader.submit(process.stdout.readline).result(timeout=5))
        if event.get("event") != "validated":
            raise RuntimeError("Synthetic validation failed.")
        warm_ms = (perf_counter() - warm) * 1000
        process.stdin.close()
        if process.wait(timeout=5) != 0:
            raise RuntimeError("Worker shutdown failed.")
        return {"ready_ms": round(ready_ms, 1), "warm_request_ms": round(warm_ms, 1)}
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.shutdown(wait=True)
        for stream in (process.stdin, process.stdout):
            stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error("Use 1 to 20 runs.")
    samples = [sample(args.root.resolve()) for _ in range(args.runs)]
    result = {"schema": 1, "scope": "model-only, ordinary user, no camera; OS file cache not flushed",
              "samples": samples, "median": {
                  key: round(statistics.median(row[key] for row in samples), 1)
                  for key in samples[0]}}
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
