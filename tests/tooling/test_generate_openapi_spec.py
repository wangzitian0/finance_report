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


def test_diff_json_paths_escapes_tokens() -> None:
    """diff_json_paths returns RFC 6901 escaped JSON pointer tokens."""
    current = {"paths": {"/api/health": {"get": {"description": "old"}}}}
    rendered = {"paths": {"/api/health": {"get": {"description": "new"}}}}
    diffs = gen.diff_json_paths(current, rendered)
    assert diffs == ["/paths/~1api~1health/get/description"]


def test_AC12_28_2_check_prints_json_pointer_diff_concisely(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """AC-platform.28.2: --check prints JSON pointer paths concisely instead of full spec."""
    large_doc = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            f"/items/{i}": {
                "get": {
                    "description": f"Description for item {i}",
                    "responses": {"200": {"description": f"Success {i}"}},
                }
            }
            for i in range(500)
        },
    }
    rendered = gen.render(large_doc)
    assert len(rendered) > 50_000

    modified_doc = dict(large_doc)
    modified_doc["paths"] = dict(large_doc["paths"])
    modified_doc["paths"]["/items/42"] = {
        "get": {
            "description": "Changed description",
            "responses": {"200": {"description": "Success 42"}},
        }
    }
    modified_rendered = gen.render(modified_doc)

    output = tmp_path / "openapi.json"
    output.write_text(modified_rendered, encoding="utf-8")
    monkeypatch.setattr(gen, "generate", lambda: rendered)

    exit_code = gen.main(["--output", str(output), "--check"])
    assert exit_code == 1

    captured = capsys.readouterr()
    err = captured.err
    assert "committed openapi.json is stale" in err
    assert "/paths/~1items~142/get/description" in err
    assert len(err) < 1000
