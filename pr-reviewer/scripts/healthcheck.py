#!/usr/bin/env python3
"""Healthcheck for pr-reviewer container.

Exits 0 if last poll was within 5 minutes, 1 otherwise.
Used by Docker HEALTHCHECK.
"""

import json
import sys
import time
from pathlib import Path

STATE_FILE = Path("/app/state/last_poll.json")
MAX_AGE_SECONDS = 300  # 5 minutes


def main():
    if not STATE_FILE.exists():
        print("No poll state file yet; assuming healthy during startup")
        sys.exit(0)

    data = json.loads(STATE_FILE.read_text())
    last_poll = data.get("last_poll", 0)
    age = time.time() - last_poll

    if age > MAX_AGE_SECONDS:
        print(f"Last poll {age:.0f}s ago (threshold: {MAX_AGE_SECONDS}s)")
        sys.exit(1)

    print(f"Healthy: last poll {age:.0f}s ago")
    sys.exit(0)


if __name__ == "__main__":
    main()
