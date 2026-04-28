from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.agents.worker import (
    _build_git_config_env,
    _build_tool_proxy_env,
    _containerize_proxy_url,
    _default_worker_docker_image,
    _parse_worker_json_output,
    _resolve_passthrough_env_values,
    _should_use_host_network_for_git_proxy,
    execute_leader_assignment,
    WorkerCodexConfig,
)
from src.runtime_settings import save_runtime_settings


def test_containerize_proxy_url_rewrites_localhost_for_docker() -> None:
    assert (
        _containerize_proxy_url("http://127.0.0.1:7890")
        == "http://host.docker.internal:7890"
    )
    assert (
        _containerize_proxy_url("socks5h://user:pass@localhost:7891")
        == "socks5h://user:pass@host.docker.internal:7891"
    )
    assert (
        _containerize_proxy_url("http://10.0.0.5:8080")
        == "http://10.0.0.5:8080"
    )


def test_parse_worker_json_output_accepts_fenced_json() -> None:
    payload = _parse_worker_json_output(
        """```json
{
  "summary": "ok",
  "verification": ["check"],
  "risks": [],
  "changed_files": ["worker_smoke.txt"],
  "workflow_updates": {}
}
```"""
    )

    assert payload == {
        "summary": "ok",
        "verification": ["check"],
        "risks": [],
        "changed_files": ["worker_smoke.txt"],
        "workflow_updates": {},
    }


def test_worker_config_uses_local_defaults(monkeypatch: object) -> None:
    monkeypatch.delenv("CODEX_WORKER_DOCKER_IMAGE", raising=False)
    monkeypatch.delenv("KIMI_WORKER_DOCKER_IMAGE", raising=False)
    monkeypatch.delenv("KIMI_WORKER_BIN", raising=False)
    monkeypatch.delenv("CODEX_WORKER_HOST_NODE_ROOT", raising=False)
    monkeypatch.setattr(
        "src.agents.worker.shutil.which",
        lambda name: (
            "/root/.nvm/versions/node/v24.14.1/bin/codex"
            if name == "codex"
            else "/root/.nvm/versions/node/v24.14.1/bin/node"
            if name == "node"
            else None
        ),
    )

    config = WorkerCodexConfig.from_env()

    assert config.docker_image == _default_worker_docker_image()
    assert config.host_node_root == "/root/.nvm/versions/node/v24.14.1"
    assert config.container_host_node_root == "/opt/host-node"
    assert config.codex_bin == "kimi"


def test_build_git_config_env_uses_git_only_proxy(monkeypatch: object) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("CODEX_WORKER_PASSTHROUGH_PROXY", raising=False)

    config = WorkerCodexConfig.from_env()
    git_env = _build_git_config_env(config, use_host_network=False)

    assert config.passthrough_proxy_env == ()
    assert git_env["GIT_CONFIG_COUNT"] == "3"
    assert git_env["GIT_CONFIG_KEY_0"] == "http.version"
    assert git_env["GIT_CONFIG_VALUE_0"] == "HTTP/1.1"
    assert git_env["GIT_CONFIG_KEY_1"] == "http.proxy"
    assert git_env["GIT_CONFIG_VALUE_1"] == "http://host.docker.internal:7890"
    assert git_env["GIT_CONFIG_KEY_2"] == "https.proxy"
    assert git_env["GIT_CONFIG_VALUE_2"] == "http://host.docker.internal:7890"


def test_build_git_config_env_preserves_loopback_proxy_for_host_network(
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    config = WorkerCodexConfig.from_env()
    git_env = _build_git_config_env(config, use_host_network=True)

    assert git_env["GIT_CONFIG_KEY_0"] == "http.version"
    assert git_env["GIT_CONFIG_VALUE_0"] == "HTTP/1.1"
    assert git_env["GIT_CONFIG_VALUE_1"] == "http://127.0.0.1:7890"
    assert git_env["GIT_CONFIG_VALUE_2"] == "http://127.0.0.1:7890"


def test_build_tool_proxy_env_rewrites_loopback_for_docker(monkeypatch: object) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:7891")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")

    config = WorkerCodexConfig.from_env()
    tool_env = _build_tool_proxy_env(config, use_host_network=False)

    assert tool_env["HTTP_PROXY"] == "http://host.docker.internal:7890"
    assert tool_env["HTTPS_PROXY"] == "http://host.docker.internal:7890"
    assert tool_env["ALL_PROXY"] == "socks5h://host.docker.internal:7891"
    assert tool_env["NO_PROXY"] == "localhost,127.0.0.1"


def test_should_use_host_network_for_loopback_git_proxy(monkeypatch: object) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    config = WorkerCodexConfig.from_env()

    assert _should_use_host_network_for_git_proxy(config) is True


def test_resolve_passthrough_env_values_uses_runtime_settings_for_github_token(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "env-token-should-not-be-used")
    monkeypatch.setenv("GH_TOKEN", "env-token-should-not-be-used")
    save_runtime_settings(github_token="runtime-settings-token")
    values = _resolve_passthrough_env_values(("GITHUB_TOKEN", "GH_TOKEN"))

    assert values["GITHUB_TOKEN"] == "runtime-settings-token"
    assert values["GH_TOKEN"] == "runtime-settings-token"


def test_resolve_passthrough_env_values_ignores_github_env_when_runtime_settings_missing(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "env-token-should-not-be-used")
    monkeypatch.setenv("GH_TOKEN", "env-token-should-not-be-used")

    values = _resolve_passthrough_env_values(("GITHUB_TOKEN", "GH_TOKEN"))

    assert "GITHUB_TOKEN" not in values
    assert "GH_TOKEN" not in values


def test_execute_leader_assignment_injects_git_proxy_not_global_proxy(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True)
    markdown = job_dir / "leader-task.md"
    json_path = job_dir / "leader-task.json"
    markdown.write_text("# task\n", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("KIMI_WORKER_DOCKER_IMAGE", "worker-image:test")
    kimi_home = tmp_path / ".kimi"
    kimi_home.mkdir()
    (kimi_home / "config.toml").write_text("default_model = \"kimi-test\"\n", encoding="utf-8")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path / "runtime-state"))
    monkeypatch.delenv("CODEX_WORKER_PASSTHROUGH_PROXY", raising=False)
    save_runtime_settings(github_token="runtime-token")
    monkeypatch.setattr(
        "src.agents.worker.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else "/usr/bin/git" if name == "git" else None,
    )
    monkeypatch.setattr("src.agents.worker.Path.home", lambda: tmp_path)

    captured: dict[str, object] = {}

    output_payload = (
        '{"summary":"ok","verification":[],"risks":[],"changed_files":[],"workflow_updates":{}}'
    )

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            captured["env"] = kwargs.get("env")
            self.stdin = SimpleNamespace(write=lambda _text: None, close=lambda: None)
            self._return_code: int | None = None
            stdout_handle = kwargs.get("stdout")
            if stdout_handle is not None:
                stdout_handle.write("")
            output_file = markdown.with_suffix(".result.txt")
            output_file.write_text(output_payload, encoding="utf-8")

        def poll(self) -> int | None:
            if self._return_code is None:
                self._return_code = 0
            return self._return_code

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self._return_code = 0
            return 0

        def terminate(self) -> None:
            self._return_code = 0

        def kill(self) -> None:
            self._return_code = 0

    monkeypatch.setattr("src.agents.worker.subprocess.Popen", FakeProcess)

    report = execute_leader_assignment(
        task_id="task-1",
        subworker_id="subworker-1",
        thread_id="thread-1",
        job_directory=str(job_dir),
        repo_url="https://github.com/acme/demo-repo.git",
        collaboration_target="https://github.com/acme/demo-repo.git",
        local_repo_path="",
        leader_task_markdown=str(markdown),
        leader_task_json=str(json_path),
        work_content="echo test",
        acceptance_criteria="done",
    )

    command = report["docker_command"]

    assert report["status"] == "completed"
    assert "--network" in command
    assert "host" in command
    assert "-e" in command
    assert "GITHUB_TOKEN" in command
    assert "GH_TOKEN" in command
    assert "GIT_CONFIG_COUNT=3" in command
    assert "GIT_CONFIG_KEY_0=http.version" in command
    assert "GIT_CONFIG_VALUE_0=HTTP/1.1" in command
    assert "GIT_CONFIG_KEY_1=http.proxy" in command
    assert "GIT_CONFIG_VALUE_1=http://127.0.0.1:7890" in command
    assert "GIT_CONFIG_KEY_2=https.proxy" in command
    assert "GIT_CONFIG_VALUE_2=http://127.0.0.1:7890" in command
    assert "--add-host" not in command
    assert "--entrypoint" in command
    assert "bash" in command
    assert "-lc" in command
    assert "codex.stdout.log" in command[-1]
    assert "codex.stderr.log" in command[-1]
    assert "codex.internal.log" in command[-1]
    assert 'KIMI_PROMPT="$(cat "$PROMPT_FILE")"' in command[-1]
    assert 'kimi --print --final-message-only -c "$KIMI_PROMPT"' in command[-1]
    assert "/host-kimi/config.toml" in command[-1]
    joined_command = " ".join(command)
    assert "-e HTTP_PROXY" not in joined_command
    assert "-e HTTPS_PROXY" not in joined_command
    assert "/host-kimi:ro" in joined_command
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GITHUB_TOKEN"] == "runtime-token"
    assert env["GH_TOKEN"] == "runtime-token"
    assert report["job_directory"] == str(job_dir.resolve())


def test_execute_leader_assignment_uses_isolated_workspace_and_proxy_wrapper(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True)
    markdown = job_dir / "leader-task.md"
    json_path = job_dir / "leader-task.json"
    markdown.write_text("# task\n", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("KIMI_WORKER_DOCKER_IMAGE", "worker-image:test")
    kimi_home = tmp_path / ".kimi"
    kimi_home.mkdir()
    (kimi_home / "config.toml").write_text("default_model = \"kimi-test\"\n", encoding="utf-8")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path / "runtime-state"))
    save_runtime_settings(github_token="runtime-token")
    monkeypatch.setattr(
        "src.agents.worker.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr("src.agents.worker.Path.home", lambda: tmp_path)

    captured: dict[str, object] = {}

    class FakeStdin:
        def __init__(self, on_close: object) -> None:
            self._parts: list[str] = []
            self._on_close = on_close

        def write(self, text: str) -> None:
            self._parts.append(text)

        def close(self) -> None:
            prompt = "".join(self._parts)
            callback = self._on_close
            if callable(callback):
                callback(prompt)

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            captured["env"] = kwargs.get("env")
            self._return_code: int | None = None
            stdout_handle = kwargs.get("stdout")
            if stdout_handle is not None:
                stdout_handle.write("")

            def finalize(prompt: str) -> None:
                captured["prompt"] = prompt
                (job_dir / "worker-created.txt").write_text(
                    "created by fake worker\n",
                    encoding="utf-8",
                )
                output_file = markdown.with_suffix(".result.txt")
                output_file.write_text(
                    (
                        '{"summary":"created file","verification":["ls worker-created.txt"],'
                        '"risks":[],"changed_files":["worker-created.txt"],'
                        '"workflow_updates":{}}'
                    ),
                    encoding="utf-8",
                )

            self.stdin = FakeStdin(finalize)

        def poll(self) -> int | None:
            if self._return_code is None:
                self._return_code = 0
            return self._return_code

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self._return_code = 0
            return 0

        def terminate(self) -> None:
            self._return_code = 0

        def kill(self) -> None:
            self._return_code = 0

    monkeypatch.setattr("src.agents.worker.subprocess.Popen", FakeProcess)

    report = execute_leader_assignment(
        task_id="task-local-repo",
        subworker_id="subworker-local-repo",
        thread_id="thread-local-repo",
        job_directory=str(job_dir),
        repo_url="",
        collaboration_target="",
        local_repo_path=str(tmp_path / "repo-should-not-be-mounted"),
        leader_task_markdown=str(markdown),
        leader_task_json=str(json_path),
        work_content="在当前仓库中新建 worker-created.txt",
        acceptance_criteria="文件已创建",
    )

    command = report["docker_command"]
    assert report["status"] == "completed"
    assert report["summary"] == "created file"
    assert report["local_repo_path"] == ""
    assert str(tmp_path / "repo") not in " ".join(command)
    assert (job_dir / "worker-created.txt").read_text(encoding="utf-8") == "created by fake worker\n"
    assert "No host repository checkout is mounted into this container." in str(captured["prompt"])
    assert "./with-proxy gh repo create" in str(captured["prompt"])
    assert "codex.stdout.log" in command[-1]
    assert "codex.stderr.log" in command[-1]
    assert "codex.internal.log" in command[-1]
    assert 'KIMI_PROMPT="$(cat "$PROMPT_FILE")"' in command[-1]
    assert 'kimi --print --final-message-only -c "$KIMI_PROMPT"' in command[-1]
    proxy_wrapper = Path(report["proxy_wrapper_path"])
    assert proxy_wrapper.is_file()
    wrapper_text = proxy_wrapper.read_text(encoding="utf-8")
    assert "export HTTP_PROXY=http://127.0.0.1:7890" in wrapper_text
    assert 'exec "$@"' in wrapper_text
