# Kimi Local Integration

This repository includes a real local-only Docker integration case for the Kimi worker path.

The goal is narrow and explicit:

- launch the real async `call_code_worker` path
- run Kimi inside Docker
- create local files in the isolated worker workspace
- return structured JSON back through the hook bus
- avoid GitHub, remote repositories, and benchmark side effects

## What It Verifies

The integration script dispatches a single worker task that must:

1. create `artifacts/local-case/report.txt`
2. create `artifacts/local-case/summary.json`
3. verify both files locally
4. return a JSON object matching the worker result schema

The script then validates:

- hook event status is `completed`
- both files exist in the worker job directory
- file contents are exact
- `structured_output` is parsed from the Kimi response

## Files

- `scripts/run_kimi_local_integration.py`
- `scripts/run_kimi_local_suite.py`
- `scripts/run_kimi_worker_contract_local.py`
- `scripts/kimi_local_suite_lib.py`
- `tests/test_kimi_local_integration.py`
- `tests/test_kimi_local_suite_lib.py`
- `configs/kimi-local-integration.env.example`

## Required Environment

You need:

- Python `>=3.11`
- `uv`
- Docker
- a prebuilt worker image, default `kimi-cliagent-benchmark:latest`
- host Kimi config at `~/.kimi/config.toml`

You can run the integration in either of these ways:

- with `~/.kimi/config.toml` already configured on the host
- with explicit `OPENAI_BASE_URL` and `OPENAI_API_KEY`

The script does not require GitHub credentials and explicitly clears:

- `GH_TOKEN`
- `GITHUB_TOKEN`

It also uses an isolated runtime state root so persisted runtime settings cannot inject a different GitHub token by accident.

## Configuration

Load the sample config and then override the secrets with your own values when needed:

```bash
set -a
source configs/kimi-local-integration.env.example
export OPENAI_BASE_URL="https://your-openai-compatible-endpoint"
export OPENAI_API_KEY="your-api-key"
set +a
```

Key variables:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `OPENAI_BASE_URL` | no | empty | Kimi provider base URL |
| `OPENAI_API_KEY` | no | empty | Kimi provider API key |
| `KIMI_WORKER_DOCKER_IMAGE` | no | `kimi-cliagent-benchmark:latest` | Worker image |
| `CODEX_WORKER_MODEL` | no | `qwen3.5-plus` | Model passed to Kimi |
| `KIMI_LOCAL_OUTPUT_ROOT` | no | `.code-terminator/kimi-local` | Local suite summary output root |
| `RUN_KIMI_LOCAL_INTEGRATION` | no | empty | Enables the real pytest entrypoint |

## Manual Run

```bash
uv run --python python3.12 python scripts/run_kimi_local_integration.py
```

Keep artifacts for inspection:

```bash
uv run --python python3.12 python scripts/run_kimi_local_integration.py --keep-artifacts
```

Pin a job root:

```bash
uv run --python python3.12 python scripts/run_kimi_local_integration.py \
  --job-root /tmp/kimi-local-integration-debug
```

Run the local suite summary:

```bash
uv run --python python3.12 python scripts/run_kimi_local_suite.py
```

Run the worker-contract local check:

```bash
uv run --python python3.12 python scripts/run_kimi_worker_contract_local.py
```

## Pytest Entry

The pytest wrapper is opt-in because it uses a real Docker container and a real model call.

```bash
RUN_KIMI_LOCAL_INTEGRATION=1 \
OPENAI_BASE_URL="https://your-openai-compatible-endpoint" \
OPENAI_API_KEY="your-api-key" \
uv run --python python3.12 pytest -q tests/test_kimi_local_integration.py
```

## Safety

This flow is designed to be local-only:

- no GitHub token is passed through
- no repo URL is supplied
- no collaboration target is supplied
- acceptance is based on local files only

If you later add GitHub-backed cases, keep them separate from this smoke test.
