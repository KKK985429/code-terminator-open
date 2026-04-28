from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_ROOT = ".code-terminator/kimi-local"
UTC = timezone.utc


@dataclass
class SuiteStepResult:
    name: str
    status: str
    exit_code: int
    elapsed_seconds: float
    command: list[str]
    notes: str = ""
    artifact: str = ""


def default_output_root(project_root: Path) -> Path:
    configured = os.getenv("KIMI_LOCAL_OUTPUT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (project_root / DEFAULT_OUTPUT_ROOT).resolve()


def host_kimi_config_path() -> Path:
    return Path.home() / ".kimi" / "config.toml"


def has_explicit_api_credentials() -> bool:
    return bool(
        os.getenv("OPENAI_BASE_URL", "").strip()
        and os.getenv("OPENAI_API_KEY", "").strip()
    )


def has_host_kimi_config() -> bool:
    return host_kimi_config_path().is_file()


def can_run_real_kimi_case() -> bool:
    return has_explicit_api_credentials() or has_host_kimi_config()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def summarize_step_counts(steps: list[SuiteStepResult]) -> dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "SKIPPED": 0}
    for step in steps:
        counts.setdefault(step.status, 0)
        counts[step.status] += 1
    counts["TOTAL"] = len(steps)
    return counts


def build_summary_payload(
    *,
    suite_name: str,
    run_id: str,
    started_at: str,
    finished_at: str,
    steps: list[SuiteStepResult],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts = summarize_step_counts(steps)
    return {
        "suite_name": suite_name,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "counts": counts,
        "metadata": metadata or {},
        "steps": [asdict(step) for step in steps],
    }


def build_summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['suite_name']}",
        "",
        f"- run_id: `{payload['run_id']}`",
        f"- started_at: `{payload['started_at']}`",
        f"- finished_at: `{payload['finished_at']}`",
        f"- total: `{payload['counts']['TOTAL']}`",
        f"- pass: `{payload['counts'].get('PASS', 0)}`",
        f"- fail: `{payload['counts'].get('FAIL', 0)}`",
        f"- skipped: `{payload['counts'].get('SKIPPED', 0)}`",
        "",
        "## Steps",
        "",
    ]
    for step in payload["steps"]:
        lines.append(
            f"- `{step['name']}`: {step['status']} "
            f"(exit={step['exit_code']}, elapsed={step['elapsed_seconds']:.2f}s)"
        )
        if step.get("notes"):
            lines.append(f"  notes: {step['notes']}")
        if step.get("artifact"):
            lines.append(f"  artifact: `{step['artifact']}`")
    return "\n".join(lines) + "\n"


def build_summary_text(payload: dict[str, Any]) -> str:
    lines = [
        f"suite_name={payload['suite_name']}",
        f"run_id={payload['run_id']}",
        f"started_at={payload['started_at']}",
        f"finished_at={payload['finished_at']}",
        f"total={payload['counts']['TOTAL']}",
        f"pass={payload['counts'].get('PASS', 0)}",
        f"fail={payload['counts'].get('FAIL', 0)}",
        f"skipped={payload['counts'].get('SKIPPED', 0)}",
    ]
    for step in payload["steps"]:
        lines.append(
            "step="
            + ",".join(
                [
                    step["name"],
                    step["status"],
                    str(step["exit_code"]),
                    f"{step['elapsed_seconds']:.2f}",
                ]
            )
        )
    return "\n".join(lines) + "\n"


def write_summary_bundle(
    *,
    output_dir: Path,
    suite_name: str,
    run_id: str,
    started_at: str,
    finished_at: str,
    steps: list[SuiteStepResult],
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = build_summary_payload(
        suite_name=suite_name,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        steps=steps,
        metadata=metadata,
    )
    json_path = output_dir / f"{suite_name}.summary.json"
    md_path = output_dir / f"{suite_name}.summary.md"
    txt_path = output_dir / f"{suite_name}.summary.txt"
    write_json(json_path, payload)
    write_text(md_path, build_summary_markdown(payload))
    write_text(txt_path, build_summary_text(payload))
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "text": str(txt_path),
    }
