#!/usr/bin/env python3
"""Container entrypoint — sync plugins then exec the target script.

Usage: python3 scripts/entrypoint.py scripts/gitea_webhook.py
       python3 scripts/entrypoint.py scripts/gh_watcher.py
"""

import os
import sys

# Sync plugins (non-fatal — container starts even if sync fails)
import sync_plugins
sync_plugins.sync()

# Exec the target script (replaces this process)
if len(sys.argv) < 2:
    print("Usage: entrypoint.py <script>", file=sys.stderr)
    sys.exit(1)

target = sys.argv[1]
os.execvp(sys.executable, [sys.executable, target] + sys.argv[2:])
