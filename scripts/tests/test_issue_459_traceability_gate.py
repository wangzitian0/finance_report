"""Issue #459 traceability gate regression tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_ac_traceability as cat  # noqa: E402


def test_stub_only_mandatory_ac_fails_traceability_gate(tmp_path, monkeypatch) -> None:
    """AC8.13.37: Stub-only mandatory ACs fail the default traceability gate."""
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "\n".join(
            [
                "version: '1.0'",
                "groups:",
                "  AC1:",
                "    AC1.1:",
                "      - id: AC1.1.1",
                "        epic: 1",
                "        epic_name: test",
                "        description: Stub-only behavior",
                "        mandatory: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    infra_registry = tmp_path / "infra.yaml"
    infra_registry.write_text("version: '1.0'\ngroups: {}\n", encoding="utf-8")
    stub_dir = tmp_path / "tests" / "_ac_stubs"
    stub_dir.mkdir(parents=True)
    (stub_dir / "test_stub.py").write_text("# AC1.1.1\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_ac_traceability.py",
            "--registry",
            str(registry),
            "--infra-registry",
            str(infra_registry),
            "--test-dirs",
            str(tmp_path / "tests"),
        ],
    )

    assert cat.main() == 1
