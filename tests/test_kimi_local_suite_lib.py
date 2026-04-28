from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kimi_local_suite_lib import (
    build_summary_payload,
    default_output_root,
    summarize_step_counts,
    SuiteStepResult,
)


def test_default_output_root_uses_env_override(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setenv("KIMI_LOCAL_OUTPUT_ROOT", str(tmp_path / "kimi-out"))

    resolved = default_output_root(PROJECT_ROOT)

    assert resolved == (tmp_path / "kimi-out").resolve()


def test_summarize_step_counts_tracks_statuses() -> None:
    steps = [
        SuiteStepResult(
            name="a", status="PASS", exit_code=0, elapsed_seconds=1.0, command=["echo", "a"]
        ),
        SuiteStepResult(
            name="b", status="FAIL", exit_code=1, elapsed_seconds=2.0, command=["echo", "b"]
        ),
        SuiteStepResult(
            name="c", status="SKIPPED", exit_code=0, elapsed_seconds=0.0, command=[]
        ),
    ]

    counts = summarize_step_counts(steps)

    assert counts == {"PASS": 1, "FAIL": 1, "SKIPPED": 1, "TOTAL": 3}


def test_build_summary_payload_preserves_metadata() -> None:
    steps = [
        SuiteStepResult(
            name="suite",
            status="PASS",
            exit_code=0,
            elapsed_seconds=1.25,
            command=["python", "script.py"],
            notes="ok",
        )
    ]

    payload = build_summary_payload(
        suite_name="kimi_local_suite",
        run_id="run-1",
        started_at="2026-04-28T10:00:00+00:00",
        finished_at="2026-04-28T10:01:00+00:00",
        steps=steps,
        metadata={"image": "kimi-cliagent-benchmark:latest"},
    )

    assert payload["suite_name"] == "kimi_local_suite"
    assert payload["counts"]["PASS"] == 1
    assert payload["metadata"]["image"] == "kimi-cliagent-benchmark:latest"
    assert payload["steps"][0]["notes"] == "ok"
