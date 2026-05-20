"""Tests para --mode CLI flag y wire en TradingAlertJob."""

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def test_cli_help_shows_mode_flag() -> None:
    result = subprocess.run(
        [PYTHON, "main.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert "--mode" in result.stdout
    assert "trader" in result.stdout
    assert "alerts_only" in result.stdout
    assert "hybrid" in result.stdout


def test_cli_rejects_invalid_mode() -> None:
    result = subprocess.run(
        [PYTHON, "main.py", "--mode", "banana", "--once"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    # argparse choices rechaza con exit code 2
    assert result.returncode != 0
    assert "banana" in (result.stderr or "") or "invalid" in (result.stderr or "").lower()
