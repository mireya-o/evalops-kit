from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

HAS_TOMLLIB = importlib.util.find_spec("tomllib") is not None


def _load_demo_module() -> ModuleType:
    workspace_root = Path(__file__).resolve().parents[1]
    script_path = workspace_root / "scripts" / "demo_golden_path.py"
    spec = importlib.util.spec_from_file_location("demo_golden_path", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_demo_script_observes_expected_pass_and_fail_behavior(tmp_path: Path) -> None:
    module = _load_demo_module()
    workspace_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "golden-path-output"

    result = module.run_demo(workspace_root=workspace_root, output_root=output_root)

    assert result.success is True
    assert result.pass_diff_exit == 0
    assert result.fail_diff_exit != 0
    assert result.pass_report.exists()
    assert result.fail_report.exists()

    pass_report = result.pass_report.read_text(encoding="utf-8")
    fail_report = result.fail_report.read_text(encoding="utf-8")
    assert "PASS `overall_avg_drop_max`" in pass_report
    assert "FAIL `" not in pass_report
    assert "FAIL `overall_avg_drop_max`" in fail_report
    assert "`case-1`" in fail_report
