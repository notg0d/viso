"""Download version-pinned recognition/landmark models and verify SHA-256."""

import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def download(url: str, target: Path, expected_hash: str | None = None) -> None:
    request = Request(url, headers={"User-Agent": "Viso-Setup/0.1"})
    temporary = target.with_suffix(target.suffix + ".partial")
    try:
        digest = hashlib.sha256()
        with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if expected_hash and digest.hexdigest() != expected_hash:
            raise RuntimeError(f"Checksum mismatch for {target.name}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    folder = ROOT / "models"
    manifest = json.loads((folder / "manifest.json").read_text())
    revision = manifest["revision"]
    (folder / "licenses").mkdir(exist_ok=True)
    for model in manifest["models"]:
        destination = folder / model["file"]
        valid = False
        if destination.exists():
            with destination.open("rb") as source:
                valid = hashlib.file_digest(source, "sha256").hexdigest() == model["sha256"]
        if valid:
            print(f"Verified {model['file']}")
        else:
            print(f"Downloading {model['file']} ({model['size'] / 1_000_000:.1f} MB)...")
            download(
                model.get("url") or f"https://media.githubusercontent.com/media/{manifest['repository']}/"
                f"{revision}/models/{model['directory']}/{model['file']}",
                destination,
                model["sha256"],
            )
        license_path = folder / "licenses" / f"{model['directory']}.txt"
        if not license_path.exists():
            download(
                model.get("license_url") or f"https://raw.githubusercontent.com/{manifest['repository']}/"
                f"{revision}/models/{model['directory']}/LICENSE",
                license_path,
            )
    print("Models are ready. Recognition runs offline.")


if __name__ == "__main__":
    main()
