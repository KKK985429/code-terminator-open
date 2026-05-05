from __future__ import annotations

import os
import re
import subprocess
from typing import Any

import httpx

from src.app.incident_registry import set_status
from src.observability import get_logger, sanitize_text
from src.runtime_settings import load_runtime_settings

logger = get_logger(__name__)

_PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)"
)


def auto_review_merge_reload(
    *,
    fingerprint: str,
    service: str,
    exception_type: str,
    traceback_summary: str,
    branch_name: str = "",
    commit_sha: str = "",
    pr_url: str = "",
) -> dict[str, Any]:
    del service, exception_type, traceback_summary, branch_name, commit_sha
    normalized_pr = pr_url.strip()
    if not normalized_pr:
        return {
            "ok": False,
            "error": "missing_pr_url",
            "message": "Worker did not return a PR URL; falling back to manual review.",
        }

    token = load_runtime_settings().github_token.strip()
    if not token:
        return {
            "ok": False,
            "error": "missing_github_token",
            "message": "GitHub token is required for automatic PR review and merge.",
        }

    review = _approve_pr(normalized_pr, token=token)
    merge = _merge_pr(normalized_pr, token=token)
    if not merge["ok"]:
        return {"ok": False, "error": "merge_failed", **merge}

    set_status(fingerprint, "approved")
    logger.info(
        "auto_review_merge.done fingerprint=%s pr_url=%s",
        fingerprint,
        sanitize_text(normalized_pr),
    )
    return {
        "ok": True,
        "action": "auto_review_merge_reload",
        "fingerprint": fingerprint,
        "pr_url": normalized_pr,
        "review": review,
        "merge": merge,
    }


def _approve_pr(pr_url: str, *, token: str) -> dict[str, Any]:
    parsed = _parse_github_pr_url(pr_url)
    if parsed:
        owner, repo, number = parsed
        response = _github_request(
            "POST",
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews",
            token=token,
            json={
                "event": "APPROVE",
                "body": "Auto-approved by code-terminator reviewer.",
            },
        )
        if response["ok"]:
            return response
        logger.warning(
            "auto_review_merge.review_api_failed pr_url=%s status=%s error=%s",
            sanitize_text(pr_url),
            response.get("status_code", ""),
            sanitize_text(str(response.get("stderr", ""))),
        )

    return _run_gh(
        [
            "gh",
            "pr",
            "review",
            pr_url,
            "--approve",
            "--body",
            "Auto-approved by code-terminator reviewer.",
        ],
        token=token,
    )


def _merge_pr(pr_url: str, *, token: str) -> dict[str, Any]:
    parsed = _parse_github_pr_url(pr_url)
    if parsed:
        owner, repo, number = parsed
        merge = _github_request(
            "PUT",
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge",
            token=token,
            json={"merge_method": "squash"},
        )
        if merge["ok"]:
            _delete_pr_branch(owner=owner, repo=repo, number=number, token=token)
        return merge

    return _run_gh(
        ["gh", "pr", "merge", pr_url, "--squash", "--delete-branch"],
        token=token,
    )


def _delete_pr_branch(*, owner: str, repo: str, number: str, token: str) -> None:
    pr = _github_request(
        "GET",
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
        token=token,
    )
    if not pr["ok"] or not isinstance(pr.get("json"), dict):
        return
    payload = pr["json"]
    head = payload.get("head", {}) if isinstance(payload, dict) else {}
    if not isinstance(head, dict):
        return
    head_repo = head.get("repo", {})
    if not isinstance(head_repo, dict):
        return
    head_owner = str(head_repo.get("owner", {}).get("login", "")).strip()
    head_repo_name = str(head_repo.get("name", "")).strip()
    head_ref = str(head.get("ref", "")).strip()
    if not head_owner or not head_repo_name or not head_ref:
        return
    encoded_ref = head_ref.replace("/", "%2F")
    _github_request(
        "DELETE",
        f"https://api.github.com/repos/{head_owner}/{head_repo_name}/git/refs/heads/{encoded_ref}",
        token=token,
    )


def _parse_github_pr_url(pr_url: str) -> tuple[str, str, str] | None:
    match = _PR_URL_RE.match(pr_url.strip())
    if match is None:
        return None
    return match.group("owner"), match.group("repo"), match.group("number")


def _github_request(
    method: str,
    url: str,
    *,
    token: str,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=30.0,
        )
    except Exception as exc:
        logger.warning("auto_review_merge.github_api_error url=%s error=%s", url, exc)
        return {"ok": False, "stdout": "", "stderr": str(exc), "status_code": 0}

    response_payload: Any = None
    if response.content:
        try:
            response_payload = response.json()
        except Exception:
            response_payload = response.text
    ok = 200 <= response.status_code < 300
    return {
        "ok": ok,
        "stdout": response.text,
        "stderr": "" if ok else response.text,
        "status_code": response.status_code,
        "json": response_payload,
    }


def _run_gh(command: list[str], *, token: str) -> dict[str, Any]:
    env = {**os.environ, "GITHUB_TOKEN": token, "GH_TOKEN": token}
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except Exception as exc:
        logger.warning("auto_review_merge.command_error command=%s error=%s", command, exc)
        return {"ok": False, "stdout": "", "stderr": str(exc), "returncode": -1}

    ok = result.returncode == 0
    logger.info(
        "auto_review_merge.command_done command=%s returncode=%s stdout=%s stderr=%s",
        command[:3],
        result.returncode,
        sanitize_text(result.stdout.strip())[:500],
        sanitize_text(result.stderr.strip())[:500],
    )
    return {
        "ok": ok,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }
