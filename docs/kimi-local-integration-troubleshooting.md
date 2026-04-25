# Kimi Local Integration Troubleshooting

## `ModuleNotFoundError: No module named 'src'`

Run the integration from repository root, or use:

```bash
uv run --python python3.12 python scripts/run_kimi_local_integration.py
```

The committed script already prepends the project root to `sys.path`.

## `Missing Kimi config at /host-kimi/config.toml`

Either:

- create and validate `~/.kimi/config.toml`
- or export `OPENAI_BASE_URL` and `OPENAI_API_KEY`

## Worker returns `completed` but `structured_output` is empty

The worker expects JSON. Kimi may wrap JSON in fenced code blocks. This repository now strips fenced markers before parsing, so update to the latest branch state if you still see this.

## Unexpected GitHub side effects

This local integration flow intentionally clears:

- `GH_TOKEN`
- `GITHUB_TOKEN`

If you still see GitHub activity, check for local script modifications or a different worker task payload.
