from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("RUN_KIMI_LOCAL_INTEGRATION", "").strip().lower()
    not in {"1", "true", "yes", "on"},
    reason="Set RUN_KIMI_LOCAL_INTEGRATION=1 to run the real local-only Kimi Docker integration case.",
)
def test_kimi_local_integration_script() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = project_root / "scripts" / "run_kimi_local_integration.py"
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Kimi local integration script failed.\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
