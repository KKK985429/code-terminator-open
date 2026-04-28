# Kimi Local Integration Artifacts

The local-only integration case writes its artifacts into the isolated worker job directory.

Expected files:

- `leader-task.md`
- `leader-task.json`
- `leader-task.result.txt`
- `codex.stdout.log`
- `codex.stderr.log`
- `codex.internal.log`
- `docker.stdout.log`
- `docker.stderr.log`
- `artifacts/local-case/report.txt`
- `artifacts/local-case/summary.json`

The script also prints the resolved job directory in its JSON output so the artifacts can be inspected after a run with `--keep-artifacts`.

Additional suite outputs are written under the local output root:

- `kimi_local_suite.summary.json`
- `kimi_local_suite.summary.md`
- `kimi_local_suite.summary.txt`
- `kimi_worker_contract_local.summary.json`
- `kimi_worker_contract_local.summary.md`
- `kimi_worker_contract_local.summary.txt`
