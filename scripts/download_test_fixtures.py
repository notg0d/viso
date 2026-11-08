"""Optional public example portraits for repeatable recognition integration tests."""

from pathlib import Path

from download_models import download

ROOT = Path(__file__).resolve().parents[1]
REVISION = "9f3061aaeed9a8756d2c970f5dfe066617a8281d"


def main():
    folder = ROOT / "tests" / ".fixtures"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("obama.jpg", "obama2.jpg", "biden.jpg"):
        target = folder / name
        if not target.exists():
            print(f"Downloading test fixture {name}...")
            download(f"https://raw.githubusercontent.com/ageitgey/face_recognition/{REVISION}/examples/{name}", target)
    print("Test portraits are ready in tests/.fixtures (excluded from git).")


if __name__ == "__main__":
    main()
