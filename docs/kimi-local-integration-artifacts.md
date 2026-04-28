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
