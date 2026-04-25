from __future__ import annotations

from pathlib import Path


def test_kimi_local_integration_assets_exist() -> None:
    root = Path(__file__).resolve().parents[2]

    assert (root / "scripts" / "run_kimi_local_integration.py").is_file()
    assert (root / "tests" / "test_kimi_local_integration.py").is_file()
    assert (root / "configs" / "kimi-local-integration.env.example").is_file()
    assert (root / "docs" / "kimi-local-integration.md").is_file()
