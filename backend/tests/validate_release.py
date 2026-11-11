"""Validate an extracted production release without copying tests into it."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess


def validate(root: Path, fixture: Path, allow_dirty: bool) -> None:
    release = json.loads((root / "RELEASE.json").read_text(encoding="utf-8"))
    assert allow_dirty or not release["source_dirty"], "Dirty draft cannot be published"
    assert release["windows_signin_installer_included"] is False
    recorded = {}
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        recorded[relative] = digest
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest, relative
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert actual == set(recorded) | {"SHA256SUMS.txt"}, "Unrecorded or missing payload files"
    assert not (root / ".viso").exists()
    assert not (root / "runtime" / "Lib" / "site-packages" / "pip").exists()
    assert not list(root.rglob("*.dpapi"))
    assert not list(root.rglob("__pycache__"))
    assert not list(root.rglob("tests"))
    assert not list(root.rglob("test_*.py"))
    assert not (root / "scripts").exists()
    assert not (root / "signin").exists()

    cwd = root.parent / "untrusted working directory"
    cwd.mkdir()
    (cwd / "cv2.py").write_text("raise RuntimeError('Working directory leaked into imports')")
    environment = dict(os.environ, PYTHONHOME=str(cwd), PYTHONPATH=str(cwd), PYTHONUSERBASE=str(cwd))
    check = r'''
import importlib.metadata as metadata
import json, pathlib, sys, tempfile
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import cv2, numpy, mediapipe
assert pathlib.Path(sys.base_prefix).resolve() == root / 'runtime', sys.base_prefix
assert sys.flags.isolated and sys.flags.dont_write_bytecode
assert not any('.venv' in entry for entry in sys.path)
for module in (cv2, numpy, mediapipe):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root / 'runtime'), module.__name__
versions = json.loads((root / 'runtime' / 'packages.json').read_text())['dependencies']
assert {d.metadata['Name'].lower().replace('_', '-'): d.version for d in metadata.distributions()} == versions
from backend.viso.recognition import FaceEngine, MODEL_ID
from backend.viso.storage import ProfileStore
engine = FaceEngine(root / 'models')
try:
    assert engine.observe(numpy.zeros((480, 640, 3), numpy.uint8)).face_count == 0
    result = engine.observe(cv2.imread(sys.argv[2]))
    assert result.face_count == 1 and result.embedding is not None, result.public()
    with tempfile.TemporaryDirectory(dir=root.parent) as folder:
        store = ProfileStore(pathlib.Path(folder))
        store.save({'name': 'Synthetic release profile', 'model_id': MODEL_ID, 'embedding': result.embedding.tolist()})
        assert b'Synthetic release profile' not in store.path.read_bytes()
        assert ProfileStore(pathlib.Path(folder)).profile['name'] == 'Synthetic release profile'
        store.clear()
        assert not store.path.exists()
finally:
    engine.close()
print('Isolated runtime, exact dependency inventory, model hashes, portrait inference and synthetic DPAPI roundtrip passed.')
'''
    result = subprocess.run([str(root / "runtime" / "python.exe"), "-I", "-B", "-c", check, str(root), str(fixture)],
                            cwd=cwd, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    print(result.stdout.strip())

    worker = subprocess.Popen([str(root / "runtime" / "python.exe"), "-I", "-B", "-u",
                               str(root / "backend" / "run_native.py"), "--ephemeral"],
                              cwd=cwd, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        assert json.loads(worker.stdout.readline()) == {"event": "ready"}
        messages = []
        while not any(item.get("event") == "engine_ready" for item in messages):
            messages.append(json.loads(worker.stdout.readline()))
        image = "data:image/jpeg;base64," + base64.b64encode(fixture.read_bytes()).decode("ascii")
        commands = [
            {"id": 1, "command": "status"},
            {"id": 2, "command": "cancel"},
            {"id": 3, "command": "image.enroll", "data": {"name": "Synthetic release profile", "images": [image]}},
            {"id": 4, "command": "image.test", "data": {"image": image}},
        ]
        output, errors = worker.communicate("\n".join(json.dumps(item) for item in commands) + "\n", timeout=30)
        assert worker.returncode == 0, errors
        messages = [json.loads(line) for line in output.splitlines()]
        assert messages[0]["result"]["engine"]["ready"], messages[0]
        assert messages[0]["result"]["profile"] is None
        assert messages[1]["result"]["state"] == "locked"
        assert messages[2]["result"]["profile"]["name"] == "Synthetic release profile", messages[2]
        assert messages[3]["result"]["attempt"]["state"] != "unlocked", messages[3]
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate()
    assert not list(root.rglob("__pycache__"))
    assert not list(root.rglob("*.dpapi"))
    print(f"Payload hashes/exclusions ({len(recorded)} files), private IPC and EOF cleanup passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    validate(args.root.resolve(), args.fixture.resolve(), args.allow_dirty)
