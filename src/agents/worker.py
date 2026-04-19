from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.app.collaboration import normalize_remote_collaboration_target
from src.app.state import AgentOutput, TaskUnit
from src.memory.longterm_chroma import LongTermChromaMemory
from src.memory.working_memory import WorkingMemory
from src.observability import get_logger, sanitize_text
from src.prompts.loader import PromptLoader
from src.runtime_settings import load_runtime_settings
from src.skills.registry import SkillRegistry
from src.tools.registry import ToolRegistry

logger = get_logger(__name__)
_DEFAULT_WORKER_DOCKER_IMAGE = "mcr.microsoft.com/playwright:v1.58.2-noble"
_PROXY_WRAPPER_NAME = "with-proxy"
WORKER_RESULT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "verification": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "changed_files": {
            "type": "array",
            "items": {"type": "string"},
        },
        "workflow_updates": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_url": {"type": "string"},
                "collaboration_target": {"type": "string"},
            },
            "required": [],
        },
    },
    "required": [
        "summary",
        "verification",
        "risks",
        "changed_files",
        "workflow_updates",
    ],
}


class WorkerExecutionError(RuntimeError):
    """Raised when the docker-backed Codex worker cannot be launched."""


@dataclass(frozen=True)
class WorkerCodexConfig:
    docker_image: str
    container_workspace: str
    codex_bin: str
    host_node_root: str
    container_host_node_root: str
    model: str
    timeout_seconds: int
    docker_args: tuple[str, ...]
    passthrough_env: tuple[str, ...]
    passthrough_proxy_env: tuple[str, ...]
    git_http_proxy: str
    git_https_proxy: str
    tool_http_proxy: str
    tool_https_proxy: str
    tool_all_proxy: str
    tool_no_proxy: str

    @classmethod
    def from_env(cls) -> WorkerCodexConfig:
        timeout_raw = os.getenv("CODEX_WORKER_TIMEOUT_SECONDS", "1800").strip() or "1800"
        try:
            timeout_seconds = max(int(timeout_raw), 60)
        except ValueError:
            timeout_seconds = 1800

        docker_args = tuple(
            shlex.split(os.getenv("CODEX_WORKER_DOCKER_ARGS", "").strip())
        )
        passthrough_env = (
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "DEFAULT_MODEL",
            "GITHUB_TOKEN",
            "GH_TOKEN",
        )
        passthrough_proxy_env = ()
        if os.getenv("CODEX_WORKER_PASSTHROUGH_PROXY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            passthrough_proxy_env = (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
            )

        git_proxy = os.getenv("CODEX_WORKER_GIT_PROXY", "").strip()
        git_http_proxy = (
            os.getenv("CODEX_WORKER_GIT_HTTP_PROXY", "").strip()
            or git_proxy
            or os.getenv("HTTP_PROXY", "").strip()
            or os.getenv("http_proxy", "").strip()
            or os.getenv("ALL_PROXY", "").strip()
            or os.getenv("all_proxy", "").strip()
        )
        git_https_proxy = (
            os.getenv("CODEX_WORKER_GIT_HTTPS_PROXY", "").strip()
            or git_proxy
            or os.getenv("HTTPS_PROXY", "").strip()
            or os.getenv("https_proxy", "").strip()
            or git_http_proxy
        )
        tool_proxy = os.getenv("CODEX_WORKER_TOOL_PROXY", "").strip()
        tool_http_proxy = (
            os.getenv("CODEX_WORKER_TOOL_HTTP_PROXY", "").strip()
            or tool_proxy
            or os.getenv("HTTP_PROXY", "").strip()
            or os.getenv("http_proxy", "").strip()
        )
        tool_https_proxy = (
            os.getenv("CODEX_WORKER_TOOL_HTTPS_PROXY", "").strip()
            or tool_proxy
            or os.getenv("HTTPS_PROXY", "").strip()
            or os.getenv("https_proxy", "").strip()
            or tool_http_proxy
        )
        tool_all_proxy = (
            os.getenv("CODEX_WORKER_TOOL_ALL_PROXY", "").strip()
            or os.getenv("ALL_PROXY", "").strip()
            or os.getenv("all_proxy", "").strip()
        )
        tool_no_proxy = (
            os.getenv("CODEX_WORKER_TOOL_NO_PROXY", "").strip()
            or os.getenv("NO_PROXY", "").strip()
            or os.getenv("no_proxy", "").strip()
        )
        return cls(
            docker_image=(
                os.getenv("CODEX_WORKER_DOCKER_IMAGE", "").strip()
                or _default_worker_docker_image()
            ),
            container_workspace=(
                os.getenv("CODEX_WORKER_CONTAINER_WORKDIR", "/workspace").strip()
                or "/workspace"
            ),
            codex_bin=os.getenv("CODEX_WORKER_CODEX_BIN", "").strip() or "codex",
            host_node_root=(
                os.getenv("CODEX_WORKER_HOST_NODE_ROOT", "").strip()
                or _default_host_node_root()
            ),
            container_host_node_root=(
                os.getenv("CODEX_WORKER_CONTAINER_NODE_ROOT", "/opt/host-node").strip()
                or "/opt/host-node"
            ),
            model=os.getenv("CODEX_WORKER_MODEL", "").strip(),
            timeout_seconds=timeout_seconds,
            docker_args=docker_args,
            passthrough_env=passthrough_env,
            passthrough_proxy_env=passthrough_proxy_env,
            git_http_proxy=git_http_proxy,
            git_https_proxy=git_https_proxy,
            tool_http_proxy=tool_http_proxy,
            tool_https_proxy=tool_https_proxy,
            tool_all_proxy=tool_all_proxy,
            tool_no_proxy=tool_no_proxy,
        )


def _default_worker_docker_image() -> str:
    return _DEFAULT_WORKER_DOCKER_IMAGE


def _candidate_node_root(binary_name: str) -> str:
    binary_path = shutil.which(binary_name)
    if not binary_path:
        return ""
    binary = Path(binary_path).expanduser()
    if binary.parent.name != "bin":
        return ""
    root = binary.parent.parent
    if not root.exists():
        return ""
    return str(root)


def _default_host_node_root() -> str:
    return _candidate_node_root("codex") or _candidate_node_root("node")


def _truncate_text(text: str, limit: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit]}..."


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise WorkerExecutionError(
            f"path {path} is outside working directory {root}"
        ) from exc


def _containerize_proxy_url(proxy_url: str) -> str:
    normalized = proxy_url.strip()
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return normalized
    netloc = parts.netloc
    if "@" in netloc:
        auth, host_port = netloc.rsplit("@", 1)
        _, _, port = host_port.partition(":")
        rewritten = f"{auth}@host.docker.internal"
        if port:
            rewritten = f"{rewritten}:{port}"
    else:
        _, _, port = netloc.partition(":")
        rewritten = "host.docker.internal"
        if port:
            rewritten = f"{rewritten}:{port}"
    return urlunsplit((parts.scheme, rewritten, parts.path, parts.query, parts.fragment))


def _proxy_targets_loopback(proxy_url: str) -> bool:
    normalized = proxy_url.strip()
    if not normalized:
        return False
    return urlsplit(normalized).hostname in {"127.0.0.1", "localhost", "::1"}


def _should_use_host_network_for_git_proxy(config: WorkerCodexConfig) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    return any(
        _proxy_targets_loopback(proxy_url)
        for proxy_url in (
            config.git_http_proxy,
            config.git_https_proxy,
            config.tool_http_proxy,
            config.tool_https_proxy,
            config.tool_all_proxy,
        )
    )


def _build_git_config_env(
    config: WorkerCodexConfig, *, use_host_network: bool = False
) -> dict[str, str]:
    entries: list[tuple[str, str]] = [("http.version", "HTTP/1.1")]
    if config.git_http_proxy:
        http_proxy = config.git_http_proxy
        if not use_host_network:
            http_proxy = _containerize_proxy_url(http_proxy)
        entries.append(("http.proxy", http_proxy))
    if config.git_https_proxy:
        https_proxy = config.git_https_proxy
        if not use_host_network:
            https_proxy = _containerize_proxy_url(https_proxy)
        entries.append(("https.proxy", https_proxy))
    env: dict[str, str] = {}
    if not entries:
        return env
    env["GIT_CONFIG_COUNT"] = str(len(entries))
    for idx, (key, value) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{idx}"] = key
        env[f"GIT_CONFIG_VALUE_{idx}"] = value
    return env


def _build_tool_proxy_env(
    config: WorkerCodexConfig, *, use_host_network: bool = False
) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in (
        ("HTTP_PROXY", config.tool_http_proxy),
        ("HTTPS_PROXY", config.tool_https_proxy),
        ("ALL_PROXY", config.tool_all_proxy),
        ("NO_PROXY", config.tool_no_proxy),
    ):
        normalized = value.strip()
        if not normalized:
            continue
        if key != "NO_PROXY" and not use_host_network:
            normalized = _containerize_proxy_url(normalized)
        env[key] = normalized
    return env


def _needs_host_gateway(command: list[str], *env_maps: dict[str, str]) -> bool:
    combined_values = " ".join(
        value for env_map in env_maps for value in env_map.values() if value
    )
    if not combined_values:
        return False
    if "host.docker.internal" not in combined_values:
        return False
    existing = " ".join(command)
    return "host.docker.internal:host-gateway" not in existing


def _has_network_option(command: list[str]) -> bool:
    for token in command:
        if token in {"--network", "--net"}:
            return True
        if token.startswith("--network=") or token.startswith("--net="):
            return True
    return False


def _resolve_passthrough_env_values(env_names: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for env_name in env_names:
        if env_name in {"GITHUB_TOKEN", "GH_TOKEN"}:
            continue
        value = os.getenv(env_name, "").strip()
        if value:
            values[env_name] = value

    github_token = load_runtime_settings().github_token.strip()
    if github_token:
        values["GITHUB_TOKEN"] = github_token
        values["GH_TOKEN"] = github_token
    return values


def _write_proxy_wrapper(
    *, job_directory: Path, proxy_env: dict[str, str]
) -> tuple[Path | None, str]:
    if not proxy_env:
        return None, ""
    wrapper_path = job_directory / _PROXY_WRAPPER_NAME
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
    ]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        value = proxy_env.get(key, "").strip()
        if not value:
            continue
        quoted = shlex.quote(value)
        lines.append(f"export {key}={quoted}")
        lines.append(f"export {key.lower()}={quoted}")
    lines.append('exec "$@"')
    wrapper_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wrapper_path.chmod(0o755)
    return wrapper_path, wrapper_path.name


def _build_leader_prompt(
    *,
    instruction_markdown_relpath: str,
    instruction_json_relpath: str,
    explicit_repo_url: str,
    explicit_collaboration_target: str,
    proxy_wrapper_relpath: str,
    work_content: str,
    acceptance_criteria: str,
) -> str:
    prompt_lines = [
        "You are the worker agent running inside an external Docker sandbox.",
        "Before doing anything, read both leader instruction files from the mounted job workspace:",
        f"- {instruction_markdown_relpath}",
        f"- {instruction_json_relpath}",
        "",
        "The mounted workspace is an isolated blank job directory, not a pre-cloned target repository.",
        "No host repository checkout is mounted into this container.",
    ]
    if proxy_wrapper_relpath:
        prompt_lines.extend(
            [
                "Codex itself is running with proxy disabled.",
                f"For networked shell tools other than git, run them through ./{proxy_wrapper_relpath} <command> ...",
                "Examples: ./with-proxy gh auth status, ./with-proxy gh repo create, ./with-proxy gh issue create, ./with-proxy gh pr create, ./with-proxy gh pr review, ./with-proxy curl ...",
                "Git already receives proxy settings via GIT_CONFIG_* and does not need the wrapper.",
                "If `gh` is unavailable in the container, use ./with-proxy curl with the GitHub REST API instead.",
                "",
            ]
        )
    prompt_lines.extend(
        [
            "You must decide from the task whether to clone an existing repository, initialize a new repository, or create/push a new remote.",
            "If explicit workflow context already includes a stable collaboration address, you may use it. Otherwise infer the required repo actions from the task itself.",
            f"Explicit repo_url: {explicit_repo_url or '(missing)'}",
            f"Explicit collaboration_target: {explicit_collaboration_target or '(missing)'}",
            "",
            "Manage Git inside the Docker workspace yourself.",
            "For GitHub collaboration tasks, prefer GitHub CLI (`gh`) over hand-written API calls when possible.",
            "Use the runtime-provided GH_TOKEN / GITHUB_TOKEN for GitHub auth.",
            "If `gh` is not installed in the current image, use `./with-proxy curl ...` against the GitHub API.",
            "If you discover or create a stable collaboration address, return it via workflow_updates.repo_url and/or workflow_updates.collaboration_target.",
            "Only return a remotely reachable Git address that another fresh worker container can clone or fetch.",
            "Do not return file:// URLs, /workspace paths, local filesystem paths, or container-only paths. If you only have a local path, leave workflow_updates empty.",
            "",
            "Leader command:",
            work_content or "(empty)",
            "",
            "Acceptance criteria:",
            acceptance_criteria or "(empty)",
            "",
            "Return ONLY a JSON object that satisfies this JSON Schema:",
            json.dumps(WORKER_RESULT_JSON_SCHEMA, ensure_ascii=False, indent=2),
            "If there are no workflow updates, return an empty object for workflow_updates.",
        ]
    )
    return "\n".join(prompt_lines)


def execute_leader_assignment(
    *,
    task_id: str,
    subworker_id: str,
    thread_id: str,
    job_directory: str,
    repo_url: str,
    collaboration_target: str,
    local_repo_path: str,
    leader_task_markdown: str,
    leader_task_json: str,
    work_content: str,
    acceptance_criteria: str,
) -> dict[str, Any]:
    """Execute a leader-assigned task by running Codex inside Docker."""

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    host_job_dir = Path(job_directory).expanduser().resolve()
    markdown_path = Path(leader_task_markdown).expanduser().resolve()
    json_path = Path(leader_task_json).expanduser().resolve()
    output_path = markdown_path.with_suffix(".result.txt")
    report: dict[str, Any] = {
        "task_id": task_id,
        "subworker_id": subworker_id,
        "thread_id": thread_id,
        "job_directory": str(host_job_dir),
        "repo_url": repo_url,
        "collaboration_target": collaboration_target,
        "local_repo_path": "",
        "leader_task_markdown": str(markdown_path),
        "leader_task_json": str(json_path),
        "result_file": str(output_path),
        "work_content": work_content,
        "acceptance_criteria": acceptance_criteria,
        "started_at": started_at,
    }

    try:
        if not host_job_dir.is_dir():
            raise WorkerExecutionError(
                f"job_directory does not exist: {host_job_dir}"
            )
        if not markdown_path.is_file():
            raise WorkerExecutionError(
                f"leader markdown instruction file is missing: {markdown_path}"
            )
        if not json_path.is_file():
            raise WorkerExecutionError(
                f"leader json instruction file is missing: {json_path}"
            )

        config = WorkerCodexConfig.from_env()
        docker_bin = shutil.which("docker")
        if docker_bin is None:
            raise WorkerExecutionError("docker binary is not available on PATH")
        if not config.docker_image:
            raise WorkerExecutionError(
                "CODEX_WORKER_DOCKER_IMAGE is not set"
            )

        instruction_markdown_relpath = _relative_to_root(markdown_path, host_job_dir)
        instruction_json_relpath = _relative_to_root(json_path, host_job_dir)
        output_relpath = _relative_to_root(output_path, host_job_dir)
        container_workspace = config.container_workspace.rstrip("/") or "/workspace"
        container_output_path = (
            Path(container_workspace) / Path(output_relpath)
        ).as_posix()
        codex_stdout_log_path = host_job_dir / "codex.stdout.log"
        codex_stderr_log_path = host_job_dir / "codex.stderr.log"
        codex_internal_log_path = host_job_dir / "codex.internal.log"
        codex_stdout_log_path.write_text("", encoding="utf-8")
        codex_stderr_log_path.write_text("", encoding="utf-8")
        codex_internal_log_path.write_text("", encoding="utf-8")
        container_codex_stdout_path = (Path(container_workspace) / "codex.stdout.log").as_posix()
        container_codex_stderr_path = (Path(container_workspace) / "codex.stderr.log").as_posix()
        container_codex_internal_path = (
            Path(container_workspace) / "codex.internal.log"
        ).as_posix()
        use_host_network = _should_use_host_network_for_git_proxy(config)
        tool_proxy_env = _build_tool_proxy_env(
            config, use_host_network=use_host_network
        )
        proxy_wrapper_path, proxy_wrapper_relpath = _write_proxy_wrapper(
            job_directory=host_job_dir,
            proxy_env=tool_proxy_env,
        )
        prompt = _build_leader_prompt(
            instruction_markdown_relpath=instruction_markdown_relpath,
            instruction_json_relpath=instruction_json_relpath,
            explicit_repo_url=repo_url,
            explicit_collaboration_target=collaboration_target,
            proxy_wrapper_relpath=proxy_wrapper_relpath,
            work_content=work_content,
            acceptance_criteria=acceptance_criteria,
        )

        command = [
            docker_bin,
            "run",
            "--rm",
            "-i",
            "-v",
            f"{host_job_dir}:{container_workspace}",
            "-w",
            container_workspace,
        ]
        codex_home = Path.home() / ".codex"
        if codex_home.exists():
            command.extend(["-v", f"{codex_home}:/root/.codex"])
        if config.host_node_root:
            host_node_root = Path(config.host_node_root).expanduser().resolve()
            if not host_node_root.exists():
                raise WorkerExecutionError(
                    f"CODEX_WORKER_HOST_NODE_ROOT does not exist: {host_node_root}"
                )
            command.extend(
                [
                    "-v",
                    f"{host_node_root}:{config.container_host_node_root}:ro",
                ]
            )
        passthrough_env_values = _resolve_passthrough_env_values(config.passthrough_env)
        for env_name in config.passthrough_env:
            if passthrough_env_values.get(env_name):
                command.extend(["-e", env_name])
        if use_host_network and not _has_network_option([*command, *config.docker_args]):
            command.extend(["--network", "host"])
        git_env = _build_git_config_env(config, use_host_network=use_host_network)
        if not use_host_network and _needs_host_gateway(command, git_env, tool_proxy_env):
            command.extend(["--add-host", "host.docker.internal:host-gateway"])
        for key, value in git_env.items():
            command.extend(["-e", f"{key}={value}"])
        command.extend(config.docker_args)
        codex_bin = config.codex_bin
        if codex_bin == "codex" and config.host_node_root:
            codex_bin = f"{config.container_host_node_root.rstrip('/')}/bin/codex"
        codex_command = [
            "/usr/bin/env",
            "-u",
            "HTTP_PROXY",
            "-u",
            "http_proxy",
            "-u",
            "HTTPS_PROXY",
            "-u",
            "https_proxy",
            "-u",
            "ALL_PROXY",
            "-u",
            "all_proxy",
            "-u",
            "NO_PROXY",
            "-u",
            "no_proxy",
            codex_bin,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-C",
            container_workspace,
            "-o",
            container_output_path,
        ]
        if config.model:
            codex_command.extend(["-m", config.model])
        codex_command.append("-")
        codex_capture_script = "\n".join(
            [
                "set -uo pipefail",
                f'LOG_SOURCE="/root/.codex/log/codex-tui.log"',
                f'CODEX_STDOUT_LOG={shlex.quote(container_codex_stdout_path)}',
                f'CODEX_STDERR_LOG={shlex.quote(container_codex_stderr_path)}',
                f'CODEX_INTERNAL_LOG={shlex.quote(container_codex_internal_path)}',
                'before_bytes=0',
                'if [ -f "$LOG_SOURCE" ]; then',
                '  before_bytes=$(wc -c < "$LOG_SOURCE" 2>/dev/null || echo 0)',
                'fi',
                ': > "$CODEX_STDOUT_LOG"',
                ': > "$CODEX_STDERR_LOG"',
                ': > "$CODEX_INTERNAL_LOG"',
                f'{shlex.join(codex_command)} >"$CODEX_STDOUT_LOG" 2>"$CODEX_STDERR_LOG"',
                'status=$?',
                'if [ -f "$LOG_SOURCE" ]; then',
                '  if [ "$before_bytes" -gt 0 ]; then',
                '    tail -c "+$((before_bytes + 1))" "$LOG_SOURCE" >"$CODEX_INTERNAL_LOG" 2>/dev/null || cp "$LOG_SOURCE" "$CODEX_INTERNAL_LOG"',
                '  else',
                '    cp "$LOG_SOURCE" "$CODEX_INTERNAL_LOG"',
                '  fi',
                'fi',
                'exit "$status"',
            ]
        )
        command.extend(
            [
                config.docker_image,
                "bash",
                "-lc",
                codex_capture_script,
            ]
        )

        stdout_log_path = host_job_dir / "docker.stdout.log"
        stderr_log_path = host_job_dir / "docker.stderr.log"
        structured_output: dict[str, Any] = {}
        final_message = ""
        forced_stop_after_result = False

        with (
            stdout_log_path.open("w+", encoding="utf-8") as stdout_handle,
            stderr_log_path.open("w+", encoding="utf-8") as stderr_handle,
        ):
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                cwd=str(host_job_dir),
                env={**os.environ, **passthrough_env_values},
            )

            if process.stdin is not None:
                try:
                    process.stdin.write(prompt)
                    process.stdin.close()
                except BrokenPipeError:
                    pass

            deadline = time.monotonic() + config.timeout_seconds
            while True:
                return_code = process.poll()
                if output_path.exists():
                    candidate = output_path.read_text(encoding="utf-8").strip()
                    if candidate:
                        final_message = candidate
                        structured_output = _parse_worker_json_output(candidate)

                if return_code is not None:
                    break

                if structured_output:
                    grace_deadline = time.monotonic() + 5.0
                    while process.poll() is None and time.monotonic() < grace_deadline:
                        time.sleep(0.2)
                    if process.poll() is None:
                        forced_stop_after_result = True
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    break

                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise subprocess.TimeoutExpired(
                        command,
                        config.timeout_seconds,
                        output=stdout_log_path.read_text(encoding="utf-8"),
                        stderr=stderr_log_path.read_text(encoding="utf-8"),
                    )

                time.sleep(0.5)

            completed = process.wait(timeout=5)
            stdout_handle.flush()
            stderr_handle.flush()
        if output_path.exists():
            final_message = output_path.read_text(encoding="utf-8").strip()
        structured_output = structured_output or _parse_worker_json_output(final_message)
        status = (
            "completed"
            if completed == 0 or forced_stop_after_result
            else "failed"
        )
        summary = (
            str(structured_output.get("summary", "")).strip()
            if structured_output
            else ""
        ) or final_message or _truncate_text(
            _read_text_if_exists(stdout_log_path)
            or _read_text_if_exists(codex_stderr_log_path)
            or _read_text_if_exists(codex_internal_log_path)
            or _read_text_if_exists(stderr_log_path)
            or "Codex finished without any output.",
            limit=3000,
        )
        report.update(
            {
                "status": status,
                "summary": summary,
                "structured_output": structured_output,
                "workflow_updates": (
                    structured_output.get("workflow_updates", {})
                    if structured_output
                    and isinstance(structured_output.get("workflow_updates"), dict)
                    else {}
                ),
                "exit_code": completed,
                "stdout_tail": _truncate_text(
                    _read_text_if_exists(stdout_log_path), limit=6000
                ),
                "stderr_tail": _truncate_text(
                    _read_text_if_exists(stderr_log_path), limit=6000
                ),
                "codex_stdout_tail": _truncate_text(
                    _read_text_if_exists(codex_stdout_log_path), limit=6000
                ),
                "codex_stderr_tail": _truncate_text(
                    _read_text_if_exists(codex_stderr_log_path), limit=6000
                ),
                "codex_internal_log_tail": _truncate_text(
                    _read_text_if_exists(codex_internal_log_path), limit=6000
                ),
                "docker_command": command,
                "proxy_wrapper_path": str(proxy_wrapper_path) if proxy_wrapper_path else "",
                "docker_stdout_log": str(stdout_log_path),
                "docker_stderr_log": str(stderr_log_path),
                "codex_stdout_log": str(codex_stdout_log_path),
                "codex_stderr_log": str(codex_stderr_log_path),
                "codex_internal_log": str(codex_internal_log_path),
                "forced_stop_after_result": forced_stop_after_result,
                "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        return report
    except subprocess.TimeoutExpired as exc:
        report.update(
            {
                "status": "failed",
                "summary": (
                    "Worker execution timed out while waiting for Codex in Docker."
                ),
                "error": f"timeout_after_seconds={exc.timeout}",
                "stdout_tail": _truncate_text(exc.stdout or "", limit=6000),
                "stderr_tail": _truncate_text(exc.stderr or "", limit=6000),
                "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        return report
    except Exception as exc:
        logger.warning(
            "worker.execute_leader_assignment.failed task_id=%s error=%s",
            task_id,
            sanitize_text(str(exc)),
        )
        report.update(
            {
                "status": "failed",
                "summary": f"Worker execution failed: {exc}",
                "error": str(exc),
                "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        return report


def _parse_worker_json_output(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "verification": _string_list(parsed.get("verification")),
        "risks": _string_list(parsed.get("risks")),
        "changed_files": _string_list(parsed.get("changed_files")),
        "workflow_updates": _normalize_worker_workflow_updates(
            parsed.get("workflow_updates")
        ),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_worker_workflow_updates(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    repo_url = normalize_remote_collaboration_target(str(value.get("repo_url", "")))
    collaboration_target = normalize_remote_collaboration_target(
        str(value.get("collaboration_target", ""))
    )
    if repo_url:
        normalized["repo_url"] = repo_url
    if collaboration_target:
        normalized["collaboration_target"] = collaboration_target
    return normalized


class WorkerAgent:
    """Worker sub-agent with a tiny ReAct-style loop."""

    def __init__(
        self,
        core_memory: dict | None = None,
        working_memory: WorkingMemory | None = None,
        longterm_memory: LongTermChromaMemory | None = None,
    ) -> None:
        self.prompt_loader = PromptLoader()
        self.tool_registry = ToolRegistry()
        self.skill_registry = SkillRegistry()
        self.core_memory = core_memory if core_memory is not None else {}
        self.working_memory = working_memory or WorkingMemory(
            role="worker", core_memory=self.core_memory
        )
        self.longterm_memory = longterm_memory or LongTermChromaMemory()
        logger.info("worker.init core_memory_keys=%s", sorted(self.core_memory.keys()))

    async def run_unit(self, unit: TaskUnit) -> AgentOutput:
        logger.info(
            "worker.run_unit.start task_id=%s title=%s details=%s",
            unit.task_id,
            sanitize_text(unit.title),
            sanitize_text(unit.details),
        )
        longterm_hits = self.longterm_memory.query(unit.details, role="worker")
        logger.info(
            "worker.run_unit.longterm task_id=%s hit_count=%s",
            unit.task_id,
            len(longterm_hits),
        )
        prompt = self.prompt_loader.load(
            "worker",
            task_id=unit.task_id,
            title=unit.title,
            details=unit.details,
            core_memory_json=json.dumps(self.core_memory, sort_keys=True),
            longterm_context=" || ".join(longterm_hits) if longterm_hits else "None",
        )

        for skill in self.skill_registry.get_skills("worker"):
            prompt = skill.before(prompt)
        self.working_memory.push(f"prompt:{unit.task_id}:{prompt}")

        tool_outputs = [
            tool.run(
                text=prompt,
                core_memory=self.core_memory,
                path=f"worker.{unit.task_id}.last_prompt",
                value=unit.details,
            )
            for tool in self.tool_registry.get_tools("worker")
        ]
        logger.info(
            "worker.run_unit.tools task_id=%s output_count=%s",
            unit.task_id,
            len(tool_outputs),
        )

        reasoning = f"Thought: analyze task {unit.task_id}\nAction: run worker tools"
        result = f"Worker completed '{unit.title}'. Tool outputs: {' | '.join(tool_outputs)}"
        self.working_memory.push(f"result:{unit.task_id}:{result}")
        summary = self.working_memory.maybe_summarize()

        for skill in self.skill_registry.get_skills("worker"):
            result = skill.after(result)

        await asyncio.sleep(0)
        output = AgentOutput(
            task_id=unit.task_id,
            role="worker",
            reasoning=reasoning,
            result=result,
            metadata={"tool_outputs": tool_outputs, "working_memory_summary": summary},
        )
        logger.info(
            "worker.run_unit.done task_id=%s result_preview=%s",
            unit.task_id,
            sanitize_text(output.result),
        )
        return output

    async def run_many(self, units: list[TaskUnit]) -> list[AgentOutput]:
        logger.info("worker.run_many.start unit_count=%s", len(units))
        coroutines = [self.run_unit(unit) for unit in units]
        outputs = list(await asyncio.gather(*coroutines))
        logger.info("worker.run_many.done output_count=%s", len(outputs))
        return outputs
