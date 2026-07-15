"""Structural locks for the staged API-surface migration (#1865 S2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.testing import api_surface_ratchet


def _write_baseline(path: Path, *, routers: list[str], schema_imports: int) -> None:
    path.write_text(
        json.dumps(
            {
                "router_files": routers,
                "package_schema_imports": schema_imports,
            }
        ),
        encoding="utf-8",
    )


def test_AC_meta_delivery_2_router_file_set_only_shrinks() -> None:
    """AC-meta.delivery.2: the transitional router directory cannot grow."""
    assert api_surface_ratchet.TERMINAL_API_HOME == "extension/api"
    assert api_surface_ratchet.main([]) == 0


def test_router_ratchet_rejects_new_file_and_update_cannot_adopt_it(
    tmp_path: Path, monkeypatch
) -> None:
    backend_src = tmp_path / "apps" / "backend" / "src"
    routers_dir = backend_src / "routers"
    routers_dir.mkdir(parents=True)
    (routers_dir / "existing.py").write_text("", encoding="utf-8")
    (routers_dir / "new.py").write_text("", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        routers=["apps/backend/src/routers/existing.py"],
        schema_imports=0,
    )

    monkeypatch.setattr(api_surface_ratchet, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(api_surface_ratchet, "BACKEND_SRC", backend_src)
    monkeypatch.setattr(api_surface_ratchet, "ROUTERS_DIR", routers_dir)
    monkeypatch.setattr(api_surface_ratchet, "BASELINE_PATH", baseline)

    assert api_surface_ratchet.main([]) == 1
    assert api_surface_ratchet.main(["--update"]) == 1
    assert json.loads(baseline.read_text(encoding="utf-8"))["router_files"] == [
        "apps/backend/src/routers/existing.py"
    ]


def test_AC_meta_delivery_3_package_schema_import_count_only_shrinks(
    tmp_path: Path, monkeypatch
) -> None:
    """AC-meta.delivery.3: package dependencies cannot expand the DTO seam."""
    backend_src = tmp_path / "apps" / "backend" / "src"
    package_file = backend_src / "reporting" / "extension" / "service.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text(
        "from src.schemas.reporting import ReportLineId\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, routers=[], schema_imports=0)

    monkeypatch.setattr(api_surface_ratchet, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(api_surface_ratchet, "BACKEND_SRC", backend_src)
    monkeypatch.setattr(api_surface_ratchet, "ROUTERS_DIR", backend_src / "routers")
    monkeypatch.setattr(api_surface_ratchet, "BASELINE_PATH", baseline)

    assert api_surface_ratchet.main([]) == 1
    assert api_surface_ratchet.main(["--update"]) == 1
    assert (
        json.loads(baseline.read_text(encoding="utf-8"))["package_schema_imports"] == 0
    )


def test_update_tightens_a_shrunk_baseline_and_validates_arguments(
    tmp_path: Path, monkeypatch
) -> None:
    backend_src = tmp_path / "apps" / "backend" / "src"
    backend_src.mkdir(parents=True)
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        routers=["apps/backend/src/routers/removed.py"],
        schema_imports=1,
    )

    monkeypatch.setattr(api_surface_ratchet, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(api_surface_ratchet, "BACKEND_SRC", backend_src)
    monkeypatch.setattr(api_surface_ratchet, "ROUTERS_DIR", backend_src / "routers")
    monkeypatch.setattr(api_surface_ratchet, "BASELINE_PATH", baseline)

    assert api_surface_ratchet.main(["--unknown"]) == 2
    assert api_surface_ratchet.main(["--update"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8")) == {
        "router_files": [],
        "package_schema_imports": 0,
    }


def test_baseline_requires_the_declared_shape_and_handles_external_paths(
    tmp_path: Path, monkeypatch
) -> None:
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr(api_surface_ratchet, "BASELINE_PATH", baseline)

    baseline.write_text('{"package_schema_imports": 0}', encoding="utf-8")
    with pytest.raises(ValueError, match="router_files"):
        api_surface_ratchet._load_baseline()

    baseline.write_text(
        '{"router_files": [1], "package_schema_imports": 0}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="router_files"):
        api_surface_ratchet._load_baseline()

    baseline.write_text(
        '{"router_files": [], "package_schema_imports": true}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="package_schema_imports"):
        api_surface_ratchet._load_baseline()

    assert api_surface_ratchet._relative_to_root(tmp_path) == str(tmp_path)
