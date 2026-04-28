from __future__ import annotations

import argparse
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
        description="Run the local Kimi Docker validation suite and write summary artifacts."
    )
    parser.add_argument(
        "--run-id",
        default=f"kimi-local-suite-{int(time.time())}",
        help="Unique run id for output artifacts.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Optional output root. Defaults to .code-terminator/kimi-local",
    )
    return parser.parse_args()


def _run_subprocess(
    *,
    name: str,
    command: list[str],
    env: dict[str, str],
    output_dir: Path,
) -> SuiteStepResult:
    started = time.time()
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.time() - started
    artifact_path = output_dir / f"{name}.log"
    write_text(
        artifact_path,
        "\n".join(
            [
                f"command={' '.join(command)}",
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
    status = "PASS" if result.returncode == 0 else "FAIL"
    return SuiteStepResult(
        name=name,
        status=status,
        exit_code=result.returncode,
        elapsed_seconds=elapsed,
        command=command,
        artifact=str(artifact_path),
    )


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
    env = os.environ.copy()
    env["RUN_KIMI_LOCAL_INTEGRATION"] = "1"
    steps: list[SuiteStepResult] = []

    if not can_run_real_kimi_case():
        steps.append(
            SuiteStepResult(
                name="kimi-local-integration",
                status="SKIPPED",
                exit_code=0,
                elapsed_seconds=0.0,
                command=[],
                notes="Missing ~/.kimi/config.toml and OPENAI_BASE_URL/OPENAI_API_KEY are not both set.",
            )
        )
    else:
        steps.append(
            _run_subprocess(
                name="kimi-local-integration",
                command=[sys.executable, "scripts/run_kimi_local_integration.py"],
                env=env,
                output_dir=output_dir,
            )
        )

    steps.append(
        _run_subprocess(
            name="kimi-local-helpers-pytest",
            command=[
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_kimi_local_integration_helpers.py",
                "tests/bootstrap/test_kimi_local_assets.py",
            ],
            env=os.environ.copy(),
            output_dir=output_dir,
        )
    )

    finished_at = now_iso()
    bundle = write_summary_bundle(
        output_dir=output_dir,
        suite_name="kimi_local_suite",
        run_id=args.run_id,
        started_at=started_at,
        finished_at=finished_at,
        steps=steps,
        metadata={"project_root": str(PROJECT_ROOT)},
    )
    print(bundle["json"])
    return 0 if all(step.status in {"PASS", "SKIPPED"} for step in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
