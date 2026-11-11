"""Launch the private desktop worker with Python's isolated mode enabled."""

from pathlib import Path
import sys

# -I excludes the working directory and PYTHONPATH. Add only our own payload root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.viso.native import main

if __name__ == "__main__":
    main()
