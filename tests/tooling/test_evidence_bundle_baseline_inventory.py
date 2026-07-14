"""Ratchet-baseline inventory (#1826 G-no-silent-baseline-aging,
AC-testing.evidence.1): every ratchet baseline in the repo is surfaced in the
evidence bundle with entry count + last-shrink date, discovered by GLOB — a
new baseline file appears with zero code changes; omitting one reds this
gate.

Split into its own file (not appended to test_evidence_bundle.py) because the
authority-classifier gate (common/meta/extension/authority_classifier.py)
keys LLM-vs-CODE detection on a per-file substring match against a small set
of record/replay-harness marker tokens; that sibling file's pre-existing
provider-corpus water-line test contains one of those tokens elsewhere in its
text. Sharing a file with it would misclassify the roadmap AC for this
deterministic glob-discovery test as driving that harness, tripping the
`testing` package's CODE-ONLY reconcile gate. Keep this file free of that
vocabulary.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.testing import evidence_bundle as eb

ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_AC_testing_evidence_1_inventory_discovers_new_baselines_by_glob(
    tmp_path: Path,
) -> None:
    """AC-testing.evidence.1: discovery is a glob, not a hand-kept list — a NEW
    baseline/exceptions file under common/ or docs/ appears in the inventory
    with zero code changes (frozen debt cannot hide from the bundle)."""
    _write_json(
        tmp_path / "common" / "testing" / "foo-baseline.json",
        {"non_value_proofs": ["a", "b"]},
    )
    before = {entry["file"] for entry in eb.ratchet_baseline_inventory(tmp_path)}
    assert before == {"common/testing/foo-baseline.json"}

    _write_json(
        tmp_path / "common" / "meta" / "data" / "new-debt-baseline.json",
        {"untagged": ["x"]},
    )
    exceptions = tmp_path / "docs" / "project" / "traceability-exceptions.md"
    exceptions.parent.mkdir(parents=True, exist_ok=True)
    exceptions.write_text(
        "| File | Class |\n|---|---|\n| r1 | infra |\n| r2 | infra |\n",
        encoding="utf-8",
    )
    after = {entry["file"] for entry in eb.ratchet_baseline_inventory(tmp_path)}
    assert after == before | {
        "common/meta/data/new-debt-baseline.json",
        "docs/project/traceability-exceptions.md",
    }


def test_baseline_inventory_reports_entry_count_and_last_shrink(
    tmp_path: Path,
) -> None:
    """Entry counts are format-aware (json list / keyed lists / scalar counters,
    jsonl lines, markdown table rows); last_shrink is None outside git."""
    _write_json(tmp_path / "common" / "t" / "list-baseline.json", ["a", "b", "c"])
    _write_json(
        tmp_path / "common" / "t" / "keyed-baseline.json",
        {"_comment": "meta ignored", "version": 1, "untagged": ["x", "y"]},
    )
    _write_json(tmp_path / "common" / "t" / "counter-baseline.json", {"total": 2917})
    jsonl = tmp_path / "common" / "t" / "scores-baseline.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text('{"a": 1}\n{"b": 2}\n\n', encoding="utf-8")
    md = tmp_path / "docs" / "x" / "grand-exceptions.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        "# Title\n\n| File | Class |\n|---|---|\n| one | a |\n| two | b |\n| three | c |\n",
        encoding="utf-8",
    )

    by_file = {
        entry["file"]: entry for entry in eb.ratchet_baseline_inventory(tmp_path)
    }
    assert by_file["common/t/list-baseline.json"]["entry_count"] == 3
    assert by_file["common/t/keyed-baseline.json"]["entry_count"] == 2
    assert by_file["common/t/counter-baseline.json"]["entry_count"] == 2917
    assert by_file["common/t/scores-baseline.jsonl"]["entry_count"] == 2
    assert by_file["docs/x/grand-exceptions.md"]["entry_count"] == 3
    for entry in by_file.values():
        assert entry["last_shrink"] is None  # tmp_path is not a git repo


def test_baseline_inventory_covers_the_repos_real_ratchet_files() -> None:
    """The real repo's known ratchet baselines are all discovered, each with an
    integer entry count and a git last-shrink timestamp."""
    inventory = eb.ratchet_baseline_inventory(ROOT)
    files = {entry["file"] for entry in inventory}
    known_ratchets = {
        "common/testing/critical-value-proof-baseline.json",
        "common/testing/mirror-assertion-baseline.json",
        "common/testing/data/ac-score-baseline.jsonl",
        "common/testing/data/protection-floor.json",
        "common/meta/data/ac-tier-baseline.json",
        "docs/project/traceability-exceptions.md",
    }
    assert known_ratchets <= files
    for entry in inventory:
        assert isinstance(entry["entry_count"], int), entry
        assert entry["last_shrink"], entry  # committed files have git history


def test_bundle_reports_every_discovered_baseline(tmp_path: Path) -> None:
    """Omitting a discovered baseline from the bundle reds this test: the
    bundle's inventory section IS the glob discovery, entry for entry."""
    _write_json(
        tmp_path / "common" / "testing" / "solo-baseline.json", {"items": ["x"]}
    )
    bundle = eb.build_evidence_bundle(tmp_path)
    assert bundle["baseline_inventory"] == eb.ratchet_baseline_inventory(tmp_path)
    assert [e["file"] for e in bundle["baseline_inventory"]] == [
        "common/testing/solo-baseline.json"
    ]


def test_render_markdown_includes_the_baseline_inventory_section(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "common" / "testing" / "solo-baseline.json", {"items": ["x", "y"]}
    )
    bundle = eb.build_evidence_bundle(tmp_path)
    rendered = eb.render_markdown(bundle)
    section_header = "### Ratchet Baseline Inventory"
    file_name = "common/testing/solo-baseline.json"
    assert section_header in rendered
    assert file_name in rendered
