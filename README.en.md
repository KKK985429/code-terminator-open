# code-terminator

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#)
[![LangGraph](https://img.shields.io/badge/LangGraph-enabled-7B61FF.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)

Language: [English](./README.en.md) | [简体中文](./README.zh-CN.md)

A minimal runnable multi-agent scaffold powered by LangGraph:

- `leader` main orchestrator
- concurrent `worker` sub-agents
- concurrent `reviewer` sub-agents
- role-scoped `tools` and `skills` extension interfaces
- role prompt template loader

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

## Setup

Choose one environment setup method and use it consistently for all Python commands.

### Option A: `uv venv` (project-local environment)

```bash
uv venv .venv
source .venv/bin/activate
uv sync
```

Optional (force uv to always use this local environment):

```bash
export UV_PROJECT_ENVIRONMENT=".venv"
```

### Option B: `conda` environment

```bash
conda create -n code-terminator python=3.11 -y
conda activate code-terminator
pip install uv
uv sync
```

Optional environment variables:

```bash
# Shared API endpoint for LLM and embeddings (leave empty for SDK default)
export OPENAI_BASE_URL=""

# Embedding model used by long-term memory retrieval
export EMBEDDING_MODEL="text-embedding-3-small"
```

## Run

Activate your environment first:

- Option A: `source .venv/bin/activate`
- Option B: `conda activate code-terminator`

Main command:

```bash
uv run python -m src.main --task "Build a TODO app backend"
```

## Web Dev Mode (Vite + FastAPI)

Run from project root:

```bash
npm install
npm --prefix web install
npm run dev
```

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- OpenAPI docs: `http://127.0.0.1:8000/docs`

`npm run dev` invokes `scripts/dev-backend.sh`, which executes `conda activate code-terminator` before starting `uvicorn`.

See API details in [`docs/api.md`](./docs/api.md).

Leader event mode examples:

```bash
# User input event (default)
uv run python -m src.main --task "Create sprint plan and issue triage"

# Mock subagent result event on existing thread
uv run python -m src.main \
  --task "resume" \
  --thread-id demo-001 \
  --resume \
  --event-type subagent_result \
  --event-task-id task-abc \
  --event-status success \
  --event-role worker \
  --event-details "implementation finished"
```

Memory-related runtime flags:

```bash
uv run python -m src.main --task "Build a TODO app backend" --thread-id demo-001
```

Resume from latest checkpoint:

```bash
uv run python -m src.main --task "Build a TODO app backend" --thread-id demo-001 --resume
```

Resume from a specific checkpoint id:

```bash
uv run python -m src.main --task "Build a TODO app backend" --thread-id demo-001 --resume --checkpoint-id <checkpoint-id>
```

## Test

Activate the same environment as in the Run section, then execute:

```bash
uv run pytest
```

Leader-specific regression suites:

```bash
uv run pytest tests/test_leader_event_runtime.py tests/test_leader_query_set.py
```

## Kimi Local Integration

This repository now includes a real local-only Kimi Docker integration case.

It verifies:

- the real async `call_code_worker` path
- Kimi execution inside Docker
- local file creation inside the isolated worker workspace
- structured JSON parsing from the Kimi response
- no GitHub usage and no remote repository usage

Config template:

```bash
configs/kimi-local-integration.env.example
```

Manual run:

```bash
set -a
source configs/kimi-local-integration.env.example
export OPENAI_BASE_URL="https://your-openai-compatible-endpoint"
export OPENAI_API_KEY="your-api-key"
set +a

uv run --python python3.12 python scripts/run_kimi_local_integration.py
```

Optional pytest entrypoint:

```bash
RUN_KIMI_LOCAL_INTEGRATION=1 \
OPENAI_BASE_URL="https://your-openai-compatible-endpoint" \
OPENAI_API_KEY="your-api-key" \
uv run --python python3.12 pytest -q tests/test_kimi_local_integration.py
```

Detailed guide:

```text
docs/kimi-local-integration.md
```

Supporting files:

```text
docs/kimi-local-integration-checklist.md
docs/kimi-local-integration-troubleshooting.md
scripts/run_kimi_local_integration.sh
configs/kimi-local-integration.dashscope.env.example
```

## Memory Storage

Memory files are stored in a local `.memory/` directory (created lazily by runtime code):

- `.memory/checkpoints.sqlite` for LangGraph checkpoint persistence
- `.memory/chroma/` for long-term vector memory (ChromaDB)

Long-term memory embeddings are generated via an OpenAI-compatible embeddings API, sharing the same `OPENAI_BASE_URL`.

Default memory constants are centralized in `src/memory/config.py`.

## Leader Plan State Machine

The leader keeps a project-management plan list with fields:

- `task_id`
- `content`
- `status` (`pending`, `in_progress`, `success`, `failed`, `rejected`)
- `details`

State transitions are validated in `src/app/plan_state_machine.py`. Invalid transitions are blocked and recorded into graph `errors`.

Minimal event-driven flow:

1. user event creates or updates plan items
2. leader generates dispatch queue for worker/reviewer CLI agents
3. mock subagent event updates task state (`pending -> in_progress -> success/failed/rejected`)
4. snapshots are persisted in core memory and checkpointed state

## Project Structure

```text
src/
  app/
    state.py          # shared state contracts
    graph.py          # langgraph workflow
  agents/
    leader.py         # task decomposition
    worker.py         # concurrent worker execution
    reviewer.py       # concurrent reviewer execution
  prompts/
    loader.py         # role template rendering
    templates/
      leader.md
      worker.md
      reviewer.md
  tools/
    base.py           # tool protocol + mock tools
    registry.py       # role-scoped tool registry
  skills/
    base.py           # skill protocol + noop skill
    registry.py       # role-scoped skill registry
  main.py             # CLI entrypoint
tests/
  test_graph_smoke.py
```
