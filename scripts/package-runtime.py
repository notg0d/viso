"""Copy the installed, pinned dependency closure; never copy an entire venv."""

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import struct
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def package(root: Path, destination: Path) -> None:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("The release requires 64-bit Windows Python.")
    site = (Path(sys.prefix) / "Lib" / "site-packages").resolve()
    if site != (root / ".venv" / "Lib" / "site-packages").resolve():
        raise RuntimeError("Run this helper with the project's .venv Python.")
    pending = [Requirement(line) for line in (root / "requirements.txt").read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    selected = {}
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        distribution = metadata.distribution(name)
        if not Path(distribution.locate_file("")).resolve().is_relative_to(site):
            raise RuntimeError(f"Dependency {name} is outside the project's environment")
        if distribution.version not in requirement.specifier:
            raise RuntimeError(f"Installed {name}=={distribution.version} does not satisfy {requirement}")
        if name in selected:
            continue
        selected[name] = distribution
        pending.extend(Requirement(value) for value in distribution.requires or [])

    output = destination / "Lib" / "site-packages"
    for name, distribution in sorted(selected.items()):
        if not distribution.files:
            raise RuntimeError(f"Missing installed file manifest for {name}")
        for relative in distribution.files:
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_relative_to(site):
                # Console scripts live outside site-packages and are not needed.
                continue
            relative = source.relative_to(site)
            if any(part in {"__pycache__", "test", "tests"} for part in relative.parts):
                continue
            if source.suffix in {".pyc", ".pyo"} or source.name == "direct_url.json":
                continue
            if not source.is_file():
                raise RuntimeError(f"Missing installed runtime file: {relative}")
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    info = {
        "python": sys.version.split()[0],
        "architecture": "windows-x64",
        "dependencies": {name: distribution.version for name, distribution in sorted(selected.items())},
    }
    (destination / "packages.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    package(args.root.resolve(), args.destination.resolve())
