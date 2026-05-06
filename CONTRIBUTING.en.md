# Contributing Guide

Thank you for contributing to `code-terminator`.

Before submitting a change, make sure the work is tied to a clear problem statement and can be reproduced, reviewed, and verified by another developer.

## Issues First

All development work should start from an Issue. Please search existing Issues before opening a new one to avoid duplicates.

### Bug Report

A bug report should include:

- Title: `[Bug]` plus a one-line summary
- Version: commit SHA, operating system, Python version, Node version if relevant
- Steps to reproduce: a minimal ordered sequence
- Expected result: what should happen
- Actual result: what happened instead
- Impact: whether it blocks a main workflow and whether a workaround exists
- Extra context: logs, screenshots, config differences, or related links

Example:

```text
[Bug] Worker runtime fails when Docker image is unavailable

Version
- commit: abcdef1
- OS: Ubuntu 24.04
- Python: 3.11

Steps to reproduce
1. Set CODEX_WORKER_DOCKER_IMAGE to a non-existing image
2. Run uv run python scripts/dispatch_real_worker_task.py

Expected result
- The CLI returns a clear configuration error

Actual result
- The process exits with an uncaught exception
```

### Feature Request

A feature request should include:

- Title: `[Feature]` plus a one-line summary
- Background: what is missing in the current workflow
- Goal: what the feature should improve and who benefits
- Proposal: core design, API changes, and constraints
- Alternatives: other approaches considered
- Acceptance criteria: measurable completion conditions
- Extra context: related Issues, design notes, logs, or discussions

Example:

```text
[Feature] Add reviewer approval status to leader event stream

Background
- The UI cannot show whether a task is waiting for review

Proposal
- Add a reviewer status field in the event payload
- Persist the field in the checkpoint snapshot

Acceptance criteria
- Backend exposes reviewer status in history API
- Web UI renders the latest reviewer state
```

## Branch Naming

Develop on a dedicated branch. Do not commit directly to `main`.

Default branch prefixes:

- `feature/<issue-id>-<short-description>` for new features and non-urgent enhancements
- `bugfix/<issue-id>-<short-description>` for bug fixes
- `hotfix/<issue-id>-<short-description>` for urgent production fixes

Rules:

- Use lowercase letters and `kebab-case`
- `issue-id` should map to an existing Issue
- Keep `short-description` concise, ideally no more than five words

Examples:

```text
feature/123-add-reviewer-status
bugfix/456-fix-history-pagination
hotfix/789-recover-worker-dispatch
```

For documentation-only work, maintainers may allow a branch such as `docs/contributing-guide`. Otherwise, use the default branch naming rules.

## Pull Request Workflow

All Pull Requests must be linked to an Issue and reviewed before being merged into `main`.

Recommended workflow:

1. Create or claim an Issue and confirm the acceptance criteria.
2. Branch from the latest `main`.
3. Implement code, documentation, and tests as needed.
4. Review the diff locally and remove unrelated changes.
5. Open a Pull Request and link the Issue, for example `Closes #123`.
6. Wait for at least one reviewer approval before merging.

A good PR description includes:

- Background and goal
- Main implementation details
- Risks and rollback plan
- Verification commands and results
- Linked Issue number

### PR Checklist

Before opening a PR, verify:

- The PR links an Issue and includes `Closes #<id>` when appropriate
- The change has a focused scope
- Documentation is updated when behavior or configuration changes
- Tests are added or updated for the changed behavior
- Relevant local verification commands pass
- No secrets, tokens, personal config, or temporary debug code are committed
- Breaking changes are clearly described in the PR body

## Commit Message Style

Use an Angular-style commit message:

```text
type(scope): subject
```

Rules:

- `type` is lowercase; common values include `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, and `ci`
- `scope` is optional; use a module name such as `api`, `worker`, or `web`
- `subject` should be concise and imperative; do not end it with a period

Examples:

```text
feat(api): add reviewer status to history response
fix(worker): handle missing docker image gracefully
docs(readme): clarify local runtime requirements
test(app): cover invalid plan state transitions
```

Recommendations:

- Keep one commit focused on one clear goal
- Avoid vague messages such as `update` or `fix stuff`
- Split large changes into reviewable commits when practical

## Code Style

Prefer the existing repository structure, naming style, and module boundaries.

General expectations:

- Python code should support `Python >= 3.11`
- Keep functions focused and avoid unrelated refactors
- Update documentation when adding public APIs, state fields, or configuration
- Keep frontend and backend field names, types, and documentation aligned
- Avoid committing generated runtime artifacts, logs, tokens, or local-only files

## Testing

Bug fixes and new features should include tests or explain why tests are not practical.

For Python changes, run:

```bash
uv run pytest
```

For targeted checks, run the most relevant tests, for example:

```bash
uv run pytest tests/test_leader_event_runtime.py tests/test_leader_query_set.py
```

For changes touching the isolated execution / Kimi integration path, run the local integration script when applicable:

```bash
uv run --python python3.12 python scripts/run_kimi_local_integration.py
```

To include the real Kimi integration pytest case, enable it explicitly:

```bash
RUN_KIMI_LOCAL_INTEGRATION=1 \
OPENAI_BASE_URL="https://your-openai-compatible-endpoint" \
OPENAI_API_KEY="your-api-key" \
uv run --python python3.12 pytest -q tests/test_kimi_local_integration.py
```

For web or full-stack changes, make sure the development environment starts:

```bash
npm run dev
```

Recommended formatting and type checks:

```bash
uv run black --check src/datagov tests/bootstrap
uv run isort --check-only src/datagov tests/bootstrap
uv run mypy --strict src
```

## Documentation

Update documentation when a change affects:

- setup steps
- environment variables
- API request or response shapes
- runtime state files
- worker configuration
- user-facing web behavior
- operational scripts

For English documentation links, use:

- [README.en.md](./README.en.md)
- [docs/api.en.md](./docs/api.en.md)
- [CONTRIBUTING.en.md](./CONTRIBUTING.en.md)

## Review Standards

Reviewers should focus on:

- correctness and regressions
- test coverage for changed behavior
- compatibility with existing runtime contracts
- security and secret handling
- failure modes and error messages
- documentation accuracy

After tests, documentation, and review requirements are satisfied, the PR can be merged according to the repository's normal workflow.
