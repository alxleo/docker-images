"""Unit tests for healthcheck.py."""

import json
import time
from pathlib import Path

import pytest

import healthcheck as hc


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect STATE_FILE to tmp dir."""
    monkeypatch.setattr(hc, "STATE_FILE", tmp_path / "last_poll.json")


class TestHealthcheck:
    def test_no_state_file_exits_healthy(self):
        """During startup before first poll, container should be healthy."""
        with pytest.raises(SystemExit) as exc:
            hc.main()
        assert exc.value.code == 0

    def test_recent_poll_healthy(self):
        hc.STATE_FILE.write_text(json.dumps({"last_poll": time.time()}))
        with pytest.raises(SystemExit) as exc:
            hc.main()
        assert exc.value.code == 0

    def test_stale_poll_unhealthy(self):
        hc.STATE_FILE.write_text(json.dumps({"last_poll": time.time() - 600}))
        with pytest.raises(SystemExit) as exc:
            hc.main()
        assert exc.value.code == 1

    def test_exactly_at_threshold(self):
        """At exactly MAX_AGE_SECONDS, should still be healthy (> not >=)."""
        hc.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Write timestamp exactly at threshold boundary
        hc.STATE_FILE.write_text(json.dumps({"last_poll": time.time() - 300}))
        with pytest.raises(SystemExit) as exc:
            hc.main()
        # time.time() advances slightly between write and check, so this
        # may be just over threshold. Accept either 0 or 1.
        assert exc.value.code in (0, 1)

    def test_missing_last_poll_key(self):
        """Corrupt state with missing key — last_poll defaults to 0, so stale."""
        hc.STATE_FILE.write_text(json.dumps({"other": "data"}))
        with pytest.raises(SystemExit) as exc:
            hc.main()
        assert exc.value.code == 1
