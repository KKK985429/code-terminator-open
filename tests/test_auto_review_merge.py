from __future__ import annotations

from typing import Any

from src.app import incident_registry
from src.app.auto_review_merge import auto_review_merge_reload
from src.app.incident_registry import get, upsert
from src.runtime_settings import save_runtime_settings


def test_auto_review_merge_requires_pr_url(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path))
    result = auto_review_merge_reload(
        fingerprint="fp-1",
        service="svc",
        exception_type="ValueError",
        traceback_summary="trace",
        pr_url="",
    )

    assert result["ok"] is False
    assert result["error"] == "missing_pr_url"


def test_auto_review_merge_creates_pr_from_branch(
    monkeypatch: Any, tmp_path: Any
) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CODE_TERMINATOR_ECOMMERCE_REPO_URL", "https://github.com/acme/repo.git")
    monkeypatch.setenv("CODE_TERMINATOR_ECOMMERCE_DEPLOY_BRANCH", "main")
    monkeypatch.setattr(
        incident_registry,
        "_REGISTRY_FILE",
        tmp_path / "incidents" / "registry.json",
    )
    save_runtime_settings(
        github_token="token-123",
        auto_review_merge_reload=True,
    )
    upsert("fp-branch", status="waiting_review", service="svc", exception_type="ValueError")

    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: Any) -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = "ok"
            self.content = b"ok"

        def json(self) -> Any:
            return self._payload

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        timeout: float,
    ) -> FakeResponse:
        del timeout
        assert headers["Authorization"] == "Bearer token-123"
        calls.append((method, url, json))
        if method == "GET" and "pulls?head=" in url:
            return FakeResponse(200, [])
        if method == "POST" and url.endswith("/pulls"):
            return FakeResponse(201, {"html_url": "https://github.com/acme/repo/pull/9"})
        if method == "GET" and url.endswith("/pulls/9"):
            return FakeResponse(
                200,
                {
                    "head": {
                        "ref": "worker-fix",
                        "repo": {"name": "repo", "owner": {"login": "acme"}},
                    }
                },
            )
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("src.app.auto_review_merge.httpx.request", fake_request)

    result = auto_review_merge_reload(
        fingerprint="fp-branch",
        service="svc",
        exception_type="ValueError",
        traceback_summary="trace",
        branch_name="worker-fix",
        commit_sha="abc123",
        pr_url="",
    )

    assert result["ok"] is True
    assert result["pr_url"] == "https://github.com/acme/repo/pull/9"
    assert calls[0] == (
        "GET",
        "https://api.github.com/repos/acme/repo/pulls?head=acme%3Aworker-fix&state=open",
        None,
    )
    assert calls[1] == (
        "POST",
        "https://api.github.com/repos/acme/repo/pulls",
        {
            "title": "fix: resolve incident fp-branch",
            "head": "worker-fix",
            "base": "main",
            "body": "Auto-generated fix for incident `fp-branch`.\n\n- Branch: `worker-fix`\n- Commit: `abc123`",
        },
    )
    assert calls[2][0] == "POST"
    assert calls[2][1] == "https://api.github.com/repos/acme/repo/pulls/9/reviews"
    assert calls[3][0] == "PUT"
    assert calls[3][1] == "https://api.github.com/repos/acme/repo/pulls/9/merge"
    assert get("fp-branch")["status"] == "approved"


def test_auto_review_merge_approves_and_merges(
    monkeypatch: Any, tmp_path: Any
) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        incident_registry,
        "_REGISTRY_FILE",
        tmp_path / "incidents" / "registry.json",
    )
    save_runtime_settings(
        github_token="token-123",
        auto_review_merge_reload=True,
    )
    upsert("fp-2", status="waiting_review", service="svc", exception_type="ValueError")

    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = "ok"
            self.content = b"ok"

        def json(self) -> dict[str, Any]:
            return self._payload

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        timeout: float,
    ) -> FakeResponse:
        del timeout
        assert headers["Authorization"] == "Bearer token-123"
        calls.append((method, url, json))
        if method == "GET":
            return FakeResponse(
                200,
                {
                    "head": {
                        "ref": "worker-fix",
                        "repo": {"name": "repo", "owner": {"login": "acme"}},
                    }
                },
            )
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("src.app.auto_review_merge.httpx.request", fake_request)

    result = auto_review_merge_reload(
        fingerprint="fp-2",
        service="svc",
        exception_type="ValueError",
        traceback_summary="trace",
        pr_url="https://github.com/acme/repo/pull/1",
    )

    assert result["ok"] is True
    assert calls[0] == (
        "POST",
        "https://api.github.com/repos/acme/repo/pulls/1/reviews",
        {"event": "APPROVE", "body": "Auto-approved by code-terminator reviewer."},
    )
    assert calls[1] == (
        "PUT",
        "https://api.github.com/repos/acme/repo/pulls/1/merge",
        {"merge_method": "squash"},
    )
    assert calls[2][0] == "GET"
    assert calls[3][0] == "DELETE"
    assert get("fp-2")["status"] == "approved"
