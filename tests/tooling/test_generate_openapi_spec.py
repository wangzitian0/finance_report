"""Contracts for the generated OpenAPI spec that drives the typed FE client (#1004)."""

from __future__ import annotations

from pathlib import Path

from common.platform import generate_openapi_spec as gen


def test_AC12_28_1_generator_emits_types_from_openapi(monkeypatch) -> None:
    """AC-platform.28.1: ``generate()`` serializes the live OpenAPI schema deterministically
    (sorted keys + trailing newline), preserving component schemas like ErrorResponse.
    """
    fake = {
        "openapi": "3.1.0",
        "paths": {"/accounts": {"get": {"responses": {"200": {}}}}},
        "components": {"schemas": {"ErrorResponse": {"type": "object"}}},
    }
    monkeypatch.setattr(gen, "_load_openapi", lambda: fake)

    rendered = gen.generate()

    assert rendered == gen.render(fake)
    assert rendered.endswith("\n")
    assert '"ErrorResponse"' in rendered
    # Deterministic: keys are sorted, so a re-render is byte-identical.
    assert gen.render(fake) == gen.render(dict(reversed(list(fake.items()))))


def test_AC12_28_2_staleness_gate_detects_drift(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """AC-platform.28.2: ``--check`` exits 0 when the committed spec matches and 1 on drift."""
    output = tmp_path / "openapi.json"
    monkeypatch.setattr(gen, "generate", lambda: '{"openapi": "3.1.0"}\n')

    output.write_text('{"openapi": "3.1.0"}\n', encoding="utf-8")
    assert gen.main(["--output", str(output), "--check"]) == 0

    output.write_text('{"openapi": "3.0.0"}\n', encoding="utf-8")
    assert gen.main(["--output", str(output), "--check"]) == 1
    assert "stale" in capsys.readouterr().err
