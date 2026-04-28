# Kimi Local Integration Checklist

Before running the real local-only Kimi integration case, confirm:

- Docker daemon is reachable
- image `kimi-cliagent-benchmark:latest` exists locally or an equivalent image is configured
- host Kimi config exists at `~/.kimi/config.toml`, or `OPENAI_BASE_URL` and `OPENAI_API_KEY` are exported
- the repository is on the intended branch
- no GitHub token is required for this test

Recommended commands:

```bash
docker images | grep kimi-cliagent-benchmark
test -f ~/.kimi/config.toml && echo KIMI_CONFIG=OK || echo KIMI_CONFIG=MISSING
uv run --python python3.12 python scripts/run_kimi_local_integration.py
```
