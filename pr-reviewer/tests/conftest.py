"""Add scripts/ to import path so we can import gh_watcher and healthcheck."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
