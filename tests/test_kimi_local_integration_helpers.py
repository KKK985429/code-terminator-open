from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_kimi_local_integration import _build_plan_item, _verify_local_artifacts


def test_build_plan_item_is_local_only() -> None:
    item = _build_plan_item()

    assert item.task_id == "task-0001"
    assert "Do not use GitHub" in item.details
    assert "Do not clone any remote repo" in item.details
    assert "artifacts/local-case/report.txt" in item.details
    assert "artifacts/local-case/summary.json" in item.details


def test_verify_local_artifacts_reads_expected_files(tmp_path: Path) -> None:
    job_directory = tmp_path
    target_dir = job_directory / "artifacts" / "local-case"
    target_dir.mkdir(parents=True)
    (target_dir / "report.txt").write_text("kimi local case ok", encoding="utf-8")
    (target_dir / "summary.json").write_text(
        json.dumps({"status": "ok", "runner": "kimi"}),
        encoding="utf-8",
    )

    payload = _verify_local_artifacts(job_directory)

    assert payload["report_file_exists"] is True
    assert payload["summary_file_exists"] is True
    assert payload["report_file_content"] == "kimi local case ok"
    assert payload["summary_file_payload"] == {"status": "ok", "runner": "kimi"}
