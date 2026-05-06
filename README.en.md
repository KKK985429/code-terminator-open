<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&height=230&color=0:00E5FF,35:7C3AED,70:FF2D75,100:FFD166&text=CODE%20TERMINATOR&fontAlign=50&fontAlignY=38&fontSize=56&fontColor=FFFFFF&desc=Autonomous%20Multi-Agent%20Software%20Runtime&descAlign=50&descAlignY=60&animation=twinkling" alt="Code Terminator hero" width="100%" />

[![Typing SVG](https://readme-typing-svg.demolab.com?font=Orbitron&weight=800&size=24&duration=2200&pause=700&color=00E5FF&center=true&vCenter=true&width=940&lines=Leader+Plans+%E2%9A%A1+Workers+Patch+%E2%9A%A1+Reviewer+Guards;Incidents+Wake+The+System+%E2%9A%A1+Agents+Fix+The+Repo;FastAPI+%2B+SSE+%2B+React+%2B+Docker+Codex+Workers)](https://git.io/typing-svg)

<p>
  <a href="./README.md">简体中文</a>
  ·
  <a href="./README.en.md">English</a>
  ·
  <a href="./docs/api.md">API Docs</a>
  ·
  <a href="./CONTRIBUTING.md">Contributing</a>
</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LangGraph-Agentic_Runtime-1C7ED6?style=for-the-badge" alt="LangGraph" />
  <img src="https://img.shields.io/badge/FastAPI-SSE_Runtime-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-Vite_Console-61DAFB?style=for-the-badge&logo=react&logoColor=20232A" alt="React" />
  <img src="https://img.shields.io/badge/Docker-Codex_Worker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/License-MIT-2EA043?style=for-the-badge&logo=open-source-initiative&logoColor=white" alt="MIT" />
</p>

<h3>From a chat bot to an observable, resumable, event-driven software engineering runtime.</h3>

</div>

---

## 🚀 Overview

`code-terminator` is a multi-agent runtime for real software engineering workflows. It is not a toy chat demo. It is built around a practical engineering loop:

```text
detect problem -> plan work -> dispatch worker -> collect result -> review output -> resume when needed
```

The project connects **LangGraph orchestration**, **FastAPI streaming APIs**, **React control console**, **Docker-isolated code workers**, **long-term memory**, **incident wakeup**, and **GitHub-native automation** into one runtime.

---

## ✨ Feature Matrix

| Module | Capability | Engineering Value |
| --- | --- | --- |
| 🧠 Leader Agent | Decomposes goals, maintains plans, calls tools | Turns one-shot chat into a stateful task machine |
| 🛠️ Worker Agent | Executes concrete code tasks | Handles implementation and repository-level work |
| 🛡️ Reviewer Agent | Reviews results and checks quality | Keeps the loop from blindly accepting generated output |
| 🌊 SSE Streaming | Streams runtime events to the web UI | Makes planning, logs, and results visible in real time |
| 🧩 Plan State Machine | Tracks pending / running / done items | Provides observable and recoverable progress |
| 🐳 Docker Codex Worker | Runs worker jobs in containers | Isolates real repository tasks from the host workspace |
| 🧬 Memory + Checkpoint | SQLite checkpoint + Chroma memory | Supports recovery, long context, and historical reuse |
| 🔔 Incident Wakeup | Converts incidents into repair work | Moves from passive chat to event-driven repair |
| 🔀 GitHub Flow | Token injection, PR fallback, automation hooks | Connects agent output with real collaboration workflows |
| ⚙️ Runtime Settings | Persists settings through UI/API | Allows runtime configuration without manual restarts |

---

## 🌌 Capability Landscape

<table>
  <tr>
    <td width="50%">
      <h3>🧠 Agentic Runtime</h3>
      <p>The Leader interprets goals, decomposes tasks, maintains plan items, invokes tools, and consumes runtime events. Worker and Reviewer agents complete the execution loop.</p>
    </td>
    <td width="50%">
      <h3>🌊 Observable Workflow</h3>
      <p>FastAPI + SSE streams conversations, plans, activity logs, and results into the React console. The runtime is designed to be watched while it works.</p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>🐳 Isolated Code Worker</h3>
      <p>Worker tasks are packaged into job bundles and can run inside Docker. Inputs, outputs, stdout, stderr, and structured results are persisted for replay and debugging.</p>
    </td>
    <td width="50%">
      <h3>🔥 Incident-Driven Repair</h3>
      <p>The system accepts incident_new and incident_regressed events. An incident can wake the Leader, create a repair plan, and dispatch a Worker.</p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>🧬 Memory & Resume</h3>
      <p>SQLite checkpoints preserve runtime state, Chroma stores long-term memory, and runtime-state keeps conversations, plans, and settings.</p>
    </td>
    <td width="50%">
      <h3>🔀 GitHub-Native Automation</h3>
      <p>Runtime settings can persist a GitHub token and inject it into Worker jobs as GITHUB_TOKEN / GH_TOKEN for branch, commit, and PR workflows.</p>
    </td>
  </tr>
</table>

---

## 🏗️ Architecture

```mermaid
flowchart TB
    USER["👤 User / Developer"] --> WEB["🎛️ React + Vite Console"]
    USER --> CLI["⌨️ CLI"]

    WEB --> API["⚡ FastAPI Runtime Service"]
    CLI --> GRAPH["🧠 LangGraph Runtime"]
    API --> GRAPH

    GRAPH --> LEADER["👑 Leader Agent"]
    LEADER --> PLAN["📋 Plan State Machine"]
    LEADER --> TOOLS["🧰 Tool Registry"]
    LEADER --> REVIEWER["🛡️ Reviewer Agent"]

    TOOLS --> WORKER_TOOL["🚀 call_code_worker_tool"]
    WORKER_TOOL --> DOCKER["🐳 Docker Codex Worker"]
    DOCKER --> REPO["📦 Target Repository"]

    API --> SSE["🌊 SSE Event Stream"]
    API --> SETTINGS["⚙️ Runtime Settings"]
    API --> HOOK["🔔 Hook Event Bus"]

    GRAPH --> CHECKPOINT["💾 SQLite Checkpoint"]
    GRAPH --> MEMORY["🧬 Chroma Long-Term Memory"]

    INCIDENT["🔥 Incident / Regression Event"] --> HOOK
    HOOK --> GRAPH

    DOCKER --> RESULT["📨 Worker Result Bundle"]
    RESULT --> HOOK
```

---

## 🧪 Runtime Flow

> Open the web console, submit an engineering task, watch the Leader create a plan, let Workers execute isolated code jobs, stream progress through SSE, persist the state, and let the Reviewer inspect the output. If an incident event arrives, the same runtime can wake up and start a repair chain.

```mermaid
sequenceDiagram
    participant U as User
    participant W as Web Console
    participant A as FastAPI
    participant G as LangGraph
    participant L as Leader
    participant D as Docker Worker
    participant R as Reviewer
    participant M as Memory

    U->>W: Submit task
    W->>A: POST /api/chat/send/stream
    A->>G: Start runtime graph
    G->>L: Plan and dispatch
    L->>D: Run isolated code task
    D-->>A: Hook event result
    A-->>W: Stream activity by SSE
    L->>R: Review worker output
    G->>M: Save checkpoint + memory
    W-->>U: Final answer + visible plan
```

---

## 🧰 Tech Stack

| Layer | Stack |
| --- | --- |
| Agent Runtime | LangGraph, LangChain, OpenAI-compatible APIs |
| Backend | FastAPI, Pydantic, Uvicorn, SSE |
| Frontend | React, Vite, TypeScript |
| Worker | Docker, Codex-compatible CLI worker, isolated job bundle |
| Memory | SQLite checkpoint, Chroma long-term memory |
| Automation | GitHub token injection, hook event bus, runtime settings |
| Quality | pytest, black, isort, mypy |

---

## ⚡ Quick Start

### 1. Requirements

- Python `3.11+`
- `uv`
- Node.js + npm
- Docker

### 2. Install Dependencies

```bash
uv sync
npm install
npm --prefix web install
```

### 3. Configure Model Access

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-openai-compatible-endpoint"
export DEFAULT_MODEL="gpt-4o-mini"
export EMBEDDING_MODEL="text-embedding-3-small"
```

### 4. Start Full Stack Dev

```bash
npm run dev
```

Default endpoints:

| Service | URL |
| --- | --- |
| Web Console | `http://127.0.0.1:5174` |
| FastAPI | `http://127.0.0.1:18000` |
| Swagger UI | `http://127.0.0.1:18000/docs` |

---

## 🖥️ Run Modes

### CLI

```bash
uv run python -m src.main --task "Build a TODO app backend"
```

Use a thread ID for recovery:

```bash
uv run python -m src.main \
  --task "Build a TODO app backend" \
  --thread-id demo-001
```

Resume a previous run:

```bash
uv run python -m src.main \
  --task "resume" \
  --thread-id demo-001 \
  --resume
```

### API

```bash
uv run uvicorn src.api.app:app --reload --host 127.0.0.1 --port 18000
```

Common endpoints:

| Endpoint | Description |
| --- | --- |
| `GET /api/health` | Health check |
| `GET /api/agents/status` | Agent status |
| `POST /api/chat/send` | Non-streaming task |
| `POST /api/chat/send/stream` | SSE streaming task |
| `GET /api/chat/history` | Chat history |
| `GET /api/conversations/{conversation_id}` | Conversation detail |
| `GET /api/conversations/{conversation_id}/plan` | Plan snapshot |
| `GET /api/settings/runtime` | Read runtime settings |
| `PUT /api/settings/runtime` | Persist runtime settings |

---

## 🎛️ Web Console

The web console is more than a chat box:

- Conversation list and history recovery
- Streaming messages
- Plan panel
- Activity log
- GitHub token settings
- SSE-driven progress updates
- Persistent conversations and plan snapshots

Run it with:

```bash
npm run dev
```

`web/vite.config.ts` proxies `/api` to the backend port. The default backend port is `18000`.

---

## 🐳 Docker Worker

Build a worker image:

```bash
docker build -t code-terminator/worker-codex -f docker/worker-codex/Dockerfile .
export CODEX_WORKER_DOCKER_IMAGE="code-terminator/worker-codex"
```

Worker jobs are persisted as bundles:

```text
.code-terminator/
  worker-jobs/
    <job-id>/
      leader-task.md
      leader-task.json
      stdout.log
      stderr.log
      result.json
```

Key settings:

| Variable | Default | Description |
| --- | --- | --- |
| `CODEX_WORKER_DOCKER_IMAGE` | `mcr.microsoft.com/playwright:v1.58.2-noble` | Worker image |
| `CODEX_WORKER_TIMEOUT_SECONDS` | `1800` | Worker timeout |
| `CODEX_WORKER_CONTAINER_WORKDIR` | `/workspace` | Container workdir |
| `CODEX_WORKER_CODEX_BIN` | `codex` | Command inside container |
| `CODEX_WORKER_MODEL` | empty | Worker model override |
| `CODEX_WORKER_JOB_ROOT` | `.code-terminator/worker-jobs` | Job bundle root |
| `CODEX_WORKER_DOCKER_ARGS` | empty | Extra args for `docker run` |

---

## 🔥 Incident Auto Dispatch

The runtime can consume incident and regression events:

1. Generate an incident fingerprint
2. Detect whether the problem is new or regressed
3. Create or update a plan item
4. Dispatch a Worker repair task
5. Receive results through hook events
6. Continue with Leader / Reviewer processing

```mermaid
flowchart LR
    LOG["Service Log / Error"] --> FP["Fingerprint"]
    FP --> REG["Incident Registry"]
    REG --> EVENT["Hook Event"]
    EVENT --> LEADER["Leader Plan"]
    LEADER --> WORKER["Worker Fix"]
    WORKER --> RESULT["Result Bundle"]
    RESULT --> REVIEW["Reviewer Check"]
    REVIEW --> DONE["Plan Updated"]
```

---

## 🧪 Built-in Test Repository: Ecommerce Platform

`ecommerce-platform/` is an independent microservice test repository used for traffic generation, fault injection, log collection, replay validation, and agent-driven repair.

It acts as a target environment for the main runtime: the runtime detects, plans, and dispatches work; the ecommerce platform provides services that can be loaded, broken, repaired, and regression-tested.

### Services

- user service
- order service
- inventory service
- payment service
- nginx gateway
- prometheus config
- traffic simulator
- local reload scripts
- service-level tests

### Local Startup

```bash
cd ecommerce-platform
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/run_local_reload_stack.sh
```

Common endpoints:

| Entry | Description |
| --- | --- |
| `/` | Gateway home |
| `/monitor` | Local monitoring dashboard |
| `/api/monitor/summary` | Monitoring summary |
| `/api/monitor/stream` | SSE monitoring stream |
| `logs/ecommerce-debug.jsonl` | Unified structured runtime log |

Stop the local stack:

```bash
bash scripts/stop_local_reload_stack.sh
```

---

## 🌊 Million-Traffic Logs & Replay

`ecommerce-platform/` includes both online traffic simulation and offline million-scale JSONL dataset generation.

### Online Traffic

```bash
cd ecommerce-platform
.venv/bin/python scripts/traffic_simulator.py --base-url http://127.0.0.1:58080
```

Locust traffic models:

```text
ecommerce-platform/traffic/locustfile.py
ecommerce-platform/traffic/shape.py
```

`shape.py` models a compressed daily access curve with morning, lunch, evening, and night traffic patterns.

### Million-Scale Offline Dataset

```bash
cd ecommerce-platform
.venv/bin/python scripts/generate_log_dataset.py \
  --output-dir logs/datasets/million-traffic-realistic \
  --gateway-records 1000000 \
  --shards 8 \
  --days 7 \
  --clean
```

The generated dataset includes:

- normal traffic
- warning traffic
- error traffic
- service exceptions with traceback
- realistic `IndexError`
- realistic `KeyError`
- realistic `AttributeError`
- realistic `TypeError`

Suggested output layout:

```text
ecommerce-platform/logs/datasets/million-traffic-realistic/
  manifest.json
  traffic-shard-01.jsonl
  traffic-shard-02.jsonl
  ...
  traffic-shard-08.jsonl
```

### Replay

```bash
cd ecommerce-platform
.venv/bin/python scripts/replay_log.py \
  --input logs/ecommerce-debug.jsonl \
  --base-url http://127.0.0.1:58080 \
  --limit 500
```

Fault switches:

| Switch | Service | Typical Failure | Trigger |
| --- | --- | --- | --- |
| `BUG_INDEX_ERROR=true` | order | `IndexError` | `GET /api/v1/orders/user/{new_user}` |
| `BUG_ORDER_COUPON_KEY=true` | order | `KeyError` | Create order with unknown `coupon_code` |
| `BUG_RACE_CONDITION=true` | inventory | `InsufficientStockError` | High-frequency concurrent orders |
| `BUG_INVENTORY_MISSING_ROW=true` | inventory | `AttributeError` | Query broken product ID |
| `BUG_FLOAT_PRECISION=true` | payment | Money precision drift | `GET /api/v1/payments/calculate` |
| `BUG_PAYMENT_GATEWAY_KEY=true` | payment | `KeyError` | Payment calculation with coupon discount |
| `BUG_NULL_VIP=true` | user | `TypeError` | New user discount request |

---

## 🧠 Memory & Recovery

```text
.memory/
  checkpoints.sqlite
  chroma/

.code-terminator/
  runtime-state/
    conversations/
    plans/
    settings/runtime.json
  hook-events/
    pending/
    processing/
  worker-jobs/
```

Supported capabilities:

- persistent conversation history
- persistent plan snapshots
- checkpoint recovery
- disk-backed hook events
- persisted GitHub token and runtime settings
- Chroma long-term memory

---

## ⚙️ Configuration

### Core Runtime

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | API key for LLM / embeddings |
| `OPENAI_BASE_URL` | empty | OpenAI-compatible endpoint |
| `DEFAULT_MODEL` | `gpt-4o-mini` | Default chat model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Long-term memory embedding model |
| `MEMORY_DATA_DIR` | `.memory` | Memory root |
| `CHECKPOINT_DB_NAME` | `checkpoints.sqlite` | Checkpoint SQLite filename |
| `CHROMA_DIR_NAME` | `chroma` | Chroma directory name |

### API / Runtime State

| Variable | Default | Description |
| --- | --- | --- |
| `CODE_TERMINATOR_API_STATE_ROOT` | `.code-terminator/runtime-state` | API runtime state root |
| `CODE_TERMINATOR_HOOK_ROOT` | `.code-terminator/hook-events` | Hook event root |
| `CODE_TERMINATOR_HOOK_STALE_SECONDS` | `30` | Stale processing event threshold |

---

## 📦 Project Layout

```text
src/
  agents/              # leader / worker / reviewer
  api/                 # FastAPI routes, models, runtime service
  app/                 # graph, state, hook bus, incident, gitops, plan state machine
  datagov/             # bootstrap package
  memory/              # checkpoint + long-term memory
  observability/       # logging helpers
  prompts/             # role templates
  skills/              # role-scoped skills
  tools/               # tool registry + worker dispatch tools
web/                   # React + Vite console
docker/worker-codex/   # Worker Dockerfile
configs/               # OpenAI-compatible / Kimi integration examples
scripts/               # dev / smoke / worker / regression scripts
docs/                  # API / logging / smoke evidence
ecommerce-platform/    # microservice test repository and traffic lab
```

Key files:

| File | Description |
| --- | --- |
| `src/app/graph.py` | Main LangGraph runtime |
| `src/agents/leader.py` | Leader Agent |
| `src/tools/call_code_worker_tool.py` | Worker dispatch tool |
| `src/api/services/runtime_service.py` | API runtime service |
| `src/app/hook_bus.py` | Hook event bus |
| `src/app/incidents.py` | Incident handling entry |
| `src/app/auto_review_merge.py` | Auto review / merge logic |
| `web/src/App.tsx` | Web console entry |

---

## ✅ Verification

```bash
uv run pytest
```

Full tests:

```bash
uv run pytest tests/
```

Format and type checks:

```bash
uv run black --check src/datagov tests/bootstrap
uv run isort --check-only src/datagov tests/bootstrap
uv run mypy --strict src
```

Important runtime tests:

```bash
uv run pytest \
  tests/test_api_integration.py \
  tests/test_hook_pump.py \
  tests/test_worker_runtime_config.py \
  tests/test_incident_auto_dispatch.py \
  tests/test_auto_review_merge.py
```

---

## 📚 Related Docs

- [API Reference](./docs/api.md)
- [Logging Guide](./docs/logging.md)
- [Auto Review Server Checklist](./docs/auto-review-server-checklist.md)
- [Kimi Local Integration](./docs/kimi-local-integration.md)
- [Environment Status](./ENV_STATUS.md)
- [Contributing](./CONTRIBUTING.md)

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&height=140&section=footer&color=0:FFD166,35:FF2D75,70:7C3AED,100:00E5FF" alt="footer" width="100%" />

<b>Code Terminator</b> · Agentic software engineering runtime for real repositories.

</div>
