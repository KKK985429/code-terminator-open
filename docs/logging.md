# Logging Guide

This project uses a shared logger with two outputs:

- Console output (always on)
- File output in `artifacts/logs/<run_tag>.log` (enabled by default)

## Run Tag

`run_tag` is attached to every log line and is used as the log filename.

Examples:

```bash
uv run python -m src.main --task "Build plan" --run-tag cli-demo
uv run python scripts/run_20_queries_real.py --run-tag real-demo
uv run python scripts/run_20_queries_concurrent.py --run-tag concurrent-demo
```

## Log Controls

Use environment variables:

```bash
export APP_LOG_LEVEL=DEBUG
export APP_LOG_FILE=1
```

- `APP_LOG_LEVEL`: logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `APP_LOG_FILE`: `1` to enable file logs, `0` to disable file logs

## Log Coverage

Detailed logs are available in:

- Agent layer: `leader`, `worker`, `reviewer`
- Runtime layer: graph invoke lifecycle and retry traces
- Memory layer: working-memory operations, long-term query/upsert flow

## Sensitive Data Handling

Known key-like tokens are redacted in logs with `***REDACTED***`.
Long values are truncated to keep logs readable.
