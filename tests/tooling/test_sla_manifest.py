"""finance_report#1654 — the machine-readable SLA manifest.

``tools/generate_sla_manifest.py`` derives a machine-readable SLA manifest
(``common/runtime/sla-manifest.generated.json``) from the same
``DEPENDENCY_MANIFEST`` that ``/health?full=1`` already asserts (#1653 consumes
that endpoint out-of-band). infra2's periodic Lark report consumes this
manifest to render an SLA row per production-required dependency instead of
hand-maintaining a second service list (finance_report#1851 G2).

Mirrors ``tests/tooling/test_required_env_manifest.py``'s drift-gate shape
(#1828 G-injection-drift-gate) for the same reason: a manifest change must not
silently drift from what infra2 renders.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools import generate_sla_manifest as gen  # noqa: E402


def _committed_manifest() -> dict:
    return json.loads(gen.SLA_MANIFEST_PATH.read_text(encoding="utf-8"))


def test_AC_runtime_sla_manifest_1_committed_manifest_matches_live_dependency_manifest():
    """AC-runtime.sla-manifest.1: the committed SLA manifest equals the manifest
    rendered from the live DEPENDENCY_MANIFEST — exact equality kills both drift
    directions (a new required dependency missing from the artifact, and a
    stale entry for a dependency that no longer requires that tier).

    Compares raw text, not just parsed JSON: infra2 consumes the committed
    file's bytes (via ``--check`` / a raw fetch), so a whitespace/key-order
    change that slipped past a parsed-JSON comparison could still desync the
    artifact from what ``generate_sla_manifest.py`` would actually produce.
    """
    rendered = gen.render_sla_manifest(gen.collect_sla_entries())
    committed = gen.SLA_MANIFEST_PATH.read_text(encoding="utf-8")

    assert committed == rendered, (
        "common/runtime/sla-manifest.generated.json is out of date with "
        "apps/backend/src/runtime/base/manifest.py. "
        "Run: python tools/generate_sla_manifest.py"
    )


def test_AC_runtime_sla_manifest_2_production_entries_are_sla_bearing_and_complete():
    """AC-runtime.sla-manifest.2: every dependency required_in(production) has
    exactly one production entry (the SLA-bearing set), naming the dependency,
    its testing kind, and a human-readable summary — enough for a periodic
    report row without re-deriving from source. workflow_engine (the 2026-07-06
    10-day crash-loop) must be present: prod-required = SLA-bearing regardless
    of whether the app feature consuming it (EPIC-019 AC19.13) has shipped."""
    committed = _committed_manifest()
    production_entries = [e for e in committed["entries"] if e["tier"] == "production"]
    names = [e["dependency"] for e in production_entries]

    assert len(names) == len(set(names)), "duplicate production SLA entry"
    assert "workflow_engine" in names, (
        "workflow_engine is required_in(production) — a prod-required "
        "dependency must carry SLA visibility even while its feature "
        "(EPIC-019 AC19.13) stays deferred"
    )
    for entry in production_entries:
        assert set(entry) == {"tier", "dependency", "kind", "summary"}
        assert entry["kind"] in {"code_dominant", "model_dominant"}
        assert entry["summary"], f"{entry['dependency']} has no SLA summary"


def test_write_mode_emits_the_manifest_artifact(tmp_path, monkeypatch):
    """The generator's write mode materializes the manifest byte-identical to
    the rendered form (so --check and write can never disagree)."""
    target = tmp_path / "sla-manifest.generated.json"
    # ROOT_DIR only feeds the relative-path print here; BACKEND_DIR (used to
    # load src.runtime) was bound at import time and stays real.
    monkeypatch.setattr(gen, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(gen, "SLA_MANIFEST_PATH", target)
    monkeypatch.setattr(sys, "argv", ["generate_sla_manifest.py"])

    assert gen.main() == 0

    written = target.read_text(encoding="utf-8")
    assert written == gen.render_sla_manifest(gen.collect_sla_entries())
    assert json.loads(written)["entries"]


def test_check_mode_reds_on_stale_manifest(tmp_path, monkeypatch, capsys):
    """--check exits 1 (with a diff) when the committed manifest is stale — the
    CLI form of the drift gate (red-team path, permanently locked)."""
    stale = tmp_path / "sla-manifest.generated.json"
    stale.write_text('{"entries": []}\n', encoding="utf-8")
    monkeypatch.setattr(gen, "SLA_MANIFEST_PATH", stale)
    monkeypatch.setattr(sys, "argv", ["generate_sla_manifest.py", "--check"])

    assert gen.main() == 1
    assert "sla-manifest.generated.json" in capsys.readouterr().out
