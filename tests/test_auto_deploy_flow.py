from __future__ import annotations

import asyncio
from typing import Any

from src.app import deploy_watcher, gitops, incident_registry
from src.app.ecommerce_target import (
    ecommerce_deploy_branch,
    ecommerce_log_file,
    ecommerce_repo_url,
    ecommerce_root,
)


def test_ecommerce_target_defaults_to_demo_repo(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.delenv("CODE_TERMINATOR_ECOMMERCE_REPO_URL", raising=False)
    monkeypatch.setenv("CODE_TERMINATOR_ECOMMERCE_ROOT", str(tmp_path / "shop"))
    monkeypatch.setenv("CODE_TERMINATOR_ECOMMERCE_DEPLOY_BRANCH", "main")

    assert ecommerce_repo_url() == "https://github.com/KKK985429/ecommerce-platform-demo.git"
    assert ecommerce_root() == tmp_path / "shop"
    assert ecommerce_deploy_branch() == "main"
    assert ecommerce_log_file() == tmp_path / "shop" / "logs" / "ecommerce-debug.jsonl"


def test_git_pull_uses_configured_deploy_branch(monkeypatch: Any) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_DEPLOY_BRANCH", "main")

    calls: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command: list[str], **kwargs: Any) -> FakeCompleted:
        del kwargs
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            completed = FakeCompleted()
            completed.stdout = "abc123"
            return completed
        return FakeCompleted()

    monkeypatch.setattr("src.app.gitops.subprocess.run", fake_run)

    result = gitops.git_pull()

    assert result["ok"] is True
    assert ["git", "pull", "--ff-only", "origin", "main"] in calls


def test_deploy_watcher_handles_approved_incident(
    monkeypatch: Any, tmp_path: Any
) -> None:
    ecommerce_root_path = tmp_path / "ecommerce-platform-demo"
    monkeypatch.setenv("CODE_TERMINATOR_ECOMMERCE_ROOT", str(ecommerce_root_path))
    monkeypatch.setenv("CODE_TERMINATOR_ECOMMERCE_DEPLOY_BRANCH", "main")
    monkeypatch.setattr(
        incident_registry,
        "_REGISTRY_FILE",
        tmp_path / "incidents" / "registry.json",
    )
    monkeypatch.setattr(deploy_watcher, "_VERIFY_WINDOW_SECONDS", 0)
    calls: dict[str, Any] = {}

    def fake_fetch(*, repo_root: Any) -> bool:
        calls["fetch_root"] = repo_root
        return True

    def fake_pull(*, branch: str, repo_root: Any) -> dict[str, Any]:
        calls["pull_branch"] = branch
        calls["pull_root"] = repo_root
        return {
            "ok": True,
            "before_sha": "abc123",
            "after_sha": "def456",
            "changed": True,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr("src.app.deploy_watcher.git_fetch", fake_fetch)
    monkeypatch.setattr("src.app.deploy_watcher.git_pull", fake_pull)
    monkeypatch.setattr("src.app.deploy_watcher._health_check", _ok_health_check)
    monkeypatch.setattr("src.app.deploy_watcher.asyncio.sleep", _fast_sleep)

    incident_registry.upsert("fp-deploy", status="approved")

    asyncio.run(deploy_watcher._handle_approved({"fingerprint": "fp-deploy"}))

    entry = incident_registry.get("fp-deploy")
    assert entry is not None
    assert entry["status"] == "resolved"
    assert entry["deployed_commit"] == "def456"
    assert calls["fetch_root"] == ecommerce_root_path
    assert calls["pull_root"] == ecommerce_root_path
    assert calls["pull_branch"] == "main"


async def _ok_health_check() -> bool:
    return True


async def _fast_sleep(seconds: float) -> None:
    del seconds
