from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scripts.kimi_local_suite_lib import (
    SuiteStepResult,
    can_run_real_kimi_case,
    default_output_root,
    now_iso,
    write_summary_bundle,
    write_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local worker-contract Kimi Docker check and save a summary."
    )
    parser.add_argument(
        "--run-id",
        default=f"kimi-worker-contract-{int(time.time())}",
        help="Unique run id for output artifacts.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Optional output root. Defaults to .code-terminator/kimi-local",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root.strip()
        else default_output_root(PROJECT_ROOT)
    )
    output_dir = output_root / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = now_iso()
    if not can_run_real_kimi_case():
        steps = [
            SuiteStepResult(
                name="worker-contract-local",
                status="SKIPPED",
                exit_code=0,
                elapsed_seconds=0.0,
                command=[],
                notes="Missing ~/.kimi/config.toml and OPENAI_BASE_URL/OPENAI_API_KEY are not both set.",
            )
        ]
        finished_at = now_iso()
        write_summary_bundle(
            output_dir=output_dir,
            suite_name="kimi_worker_contract_local",
            run_id=args.run_id,
            started_at=started_at,
            finished_at=finished_at,
            steps=steps,
            metadata={"project_root": str(PROJECT_ROOT)},
        )
        return 0

    env = os.environ.copy()
    started = time.time()
    result = subprocess.run(
        [sys.executable, "scripts/run_kimi_local_integration.py", "--keep-artifacts"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.time() - started

    raw_artifact = output_dir / "worker_contract.raw.log"
    write_text(
        raw_artifact,
        "\n".join(
            [
                f"exit_code={result.returncode}",
                "",
                "=== stdout ===",
                result.stdout,
                "",
                "=== stderr ===",
                result.stderr,
            ]
        ),
    )

    parsed_details: dict[str, object] = {}
    for stream in (result.stdout.splitlines(), result.stderr.splitlines()):
        for line in stream:
            line = line.strip()
            if not line.startswith("{") or not line.endswith("}"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "kept_job_root" in payload:
                parsed_details["kept_job_root"] = payload["kept_job_root"]

    steps = [
        SuiteStepResult(
            name="worker-contract-local",
            status="PASS" if result.returncode == 0 else "FAIL",
            exit_code=result.returncode,
            elapsed_seconds=elapsed,
            command=[sys.executable, "scripts/run_kimi_local_integration.py", "--keep-artifacts"],
            artifact=str(raw_artifact),
            notes=(
                f"kept_job_root={parsed_details.get('kept_job_root', '')}"
                if parsed_details.get("kept_job_root")
                else ""
            ),
        )
    ]

    finished_at = now_iso()
    write_summary_bundle(
        output_dir=output_dir,
        suite_name="kimi_worker_contract_local",
        run_id=args.run_id,
        started_at=started_at,
        finished_at=finished_at,
        steps=steps,
        metadata={"project_root": str(PROJECT_ROOT), **parsed_details},
    )
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
