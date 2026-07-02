"""Issue #459 traceability gate regression tests.

Exercises the surviving pure-library path (``run_traceability`` +
``traceability_failure_messages``) that the single consolidated gate
(``tools/check_ac_index.py`` -> ``check_ac_index.check_repo_contracts``) calls,
rather than a retired standalone ``main()``.
"""

from __future__ import annotations

from pathlib import Path

from common.testing import check_ac_traceability as cat


def test_stub_only_mandatory_ac_fails_traceability_gate(tmp_path: Path) -> None:
    """AC8.13.37: Stub-only mandatory ACs fail the traceability contract."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ac_registry.yaml").write_text(
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
    (docs / "infra_registry.yaml").write_text(
        "version: '1.0'\ngroups: {}\n", encoding="utf-8"
    )
    # The only reference lives in an _ac_stubs file -> stub-only, not real proof.
    stub_dir = tmp_path / "tests" / "tooling" / "_ac_stubs"
    stub_dir.mkdir(parents=True)
    (stub_dir / "test_stub.py").write_text("# AC1.1.1\n", encoding="utf-8")

    result = cat.run_traceability(tmp_path)
    assert result.stub_only == ["AC1.1.1"]
    messages = cat.traceability_failure_messages(result)
    assert any("covered only by _ac_stubs" in message for message in messages)
