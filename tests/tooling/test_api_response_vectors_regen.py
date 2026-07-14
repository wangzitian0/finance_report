"""Tooling-scope proof of the API response vector regen builders (#1827).

The authoritative wire-drift tests live in
``apps/backend/tests/schemas/test_api_response_vectors.py`` (backend suite).
This file exercises the same builders inside the tooling suite so the regen
CLI itself (``tools/api_response_vectors.py``) is executed where the tooling
coverage gate can see it, and so a vectors/builders mismatch also reds the
cheap tooling lane.
"""

from __future__ import annotations

import importlib
import json
import sys

from tools import api_response_vectors as arv


def test_build_vector_files_matches_every_committed_vectors_json() -> None:
    """AC-reporting.api-vectors.1 AC-ledger.api-vectors.1
    AC-extraction.api-vectors.1: the committed files are exactly what the
    builders produce."""
    files = arv.build_vector_files()
    assert len(files) == 3
    for path, payload in files.items():
        assert path.exists(), f"missing committed vector file: {path}"
        assert json.loads(path.read_text(encoding="utf-8")) == payload, (
            f"{path} drifted from tools/api_response_vectors.py output — "
            "regenerate via `apps/backend/.venv/bin/python tools/api_response_vectors.py`"
        )


def test_main_rewrites_vector_files(tmp_path, monkeypatch, capsys) -> None:
    target = tmp_path / "pkg" / "conformance" / "vectors.json"
    monkeypatch.setattr(arv, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(arv, "build_vector_files", lambda: {target: {"probe": 1}})

    assert arv.main() == 0

    assert json.loads(target.read_text(encoding="utf-8")) == {"probe": 1}
    out = capsys.readouterr().out
    assert out.strip().startswith("wrote ")


def test_bootstrap_inserts_backend_root_when_missing(monkeypatch) -> None:
    backend_root = str(arv.BACKEND_ROOT)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != backend_root])
    importlib.reload(arv)
    assert backend_root in sys.path
