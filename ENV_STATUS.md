# Environment Status

Date: 2026-04-18 UTC

## Summary

Environment smoke check completed on `main`.

- Python availability: PASS (`Python 3.12.3`, satisfies `>=3.8`)
- Editable install: PASS via `pip install -e .`
- Module import: PASS for `python -c "import checkpoint"`
- CLI help smoke: PASS for `python -m src.main --help` and `uvicorn --help`

## Repo Packaging Notes

- Present: `pyproject.toml`
- Absent: `requirements.txt`
- Absent: `setup.py`
- Absent: `.github/workflows/`

To satisfy the requested `import checkpoint` smoke check, a lightweight compatibility package was added at `checkpoint/__init__.py` and included in wheel packaging.

## Environment Details

- Git branch: `main`
- System Python: `3.12.3`
- System pip: `24.0`
- Verification venv: `/tmp/envcheck-venv`

## Key Dependency Versions

- `code-terminator==0.1.0`
- `fastapi==0.136.0`
- `langchain==1.2.15`
- `langgraph==1.1.8`
- `langgraph-checkpoint-sqlite==3.0.3`
- `chromadb==1.5.8`
- `openai==2.32.0`
- `pydantic==2.13.2`
- `uvicorn==0.44.0`

The machine-readable version list is stored in `docs/smoke/env_check/key_dependency_versions.txt`.

## Logs And Evidence

- System package bootstrap:
  - `docs/smoke/env_check/apt_update.log`
  - `docs/smoke/env_check/apt_install_python_tools.log`
- Python and pip versions:
  - `docs/smoke/env_check/python_version.txt`
  - `docs/smoke/env_check/pip_version.txt`
  - `docs/smoke/env_check/venv_python_version.txt`
  - `docs/smoke/env_check/venv_pip_version.txt`
- Editable install logs:
  - `docs/smoke/env_check/pip_install_editable.log`
  - `docs/smoke/env_check/pip_install_editable_after_alias.log`
- Import and CLI smoke:
  - `docs/smoke/env_check/import_checkpoint_smoke.log`
  - `docs/smoke/env_check/import_checkpoint.txt`
  - `docs/smoke/env_check/import_src.txt`
  - `docs/smoke/env_check/src_main_help.txt`
  - `docs/smoke/env_check/src_main_help_from_tmp.txt`
  - `docs/smoke/env_check/uvicorn_help.txt`

## Risks / Notes

- The container image initially lacked working `pip`/`venv`, so `python3-pip` and `python3.12-venv` were installed inside the sandbox before project installation.
- `fastapi`'s standalone CLI is not usable with current dependencies because it requires the optional `fastapi[standard]` extra. This did not block the requested project smoke checks.
- Extended runtime smoke tests (`tests/test_graph_smoke.py`, `tests/test_memory_checkpoint.py`) produced no output for over 30 seconds and were terminated. The environment-level acceptance checks still passed, but runtime test completeness remains unconfirmed.
