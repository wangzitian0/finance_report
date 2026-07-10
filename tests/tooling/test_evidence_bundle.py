"""Shared CI/nightly evidence bundle (#1690, gate re-architecture Phase 4).

Covers common.testing.evidence_bundle: the per-water-line readers (each
tolerant of a missing baseline file), the bundle assembler, the markdown
renderer, the CLI, and the drift checks anchoring the hand-maintained gate map
to the live ci.yml job graph plus both real workflow producers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from common.testing import evidence_bundle as eb

ROOT = Path(__file__).resolve().parents[2]


def assert_pyyaml_installed_before_generator(
    commands: str, generator_script: str
) -> None:
    """ac_tier_water_line() -> check_ac_tier_baseline -> generate_ac_registry ->
    ac_registry_format needs PyYAML at import time; both producer jobs use a
    bare setup-python step (no project dependency install), so a missing
    `pip install pyyaml` crashes the generator with ModuleNotFoundError before
    it ever runs (caught live on main's first real evidence-bundle run, #1690
    follow-up) — this must run BEFORE the generator, not just be present."""
    install_marker = "pip install --quiet pyyaml"
    assert install_marker in commands
    assert commands.index(install_marker) < commands.index(generator_script)


# --------------------------------------------------------------------------- #
# Per-water-line readers — each tolerant of a missing/empty baseline.
# --------------------------------------------------------------------------- #
def test_coverage_water_line_is_unavailable_when_missing(tmp_path: Path) -> None:
    result = eb.coverage_water_line(tmp_path)
    assert result == {"available": False}


def test_coverage_water_line_reads_the_committed_shape(tmp_path: Path) -> None:
    payload = {
        "coverage_percent": 87.5,
        "breakdown": {"backend": {"coverage_percent": 90.0}},
    }
    (tmp_path / "unified-coverage.json").write_text(json.dumps(payload))
    result = eb.coverage_water_line(tmp_path)
    assert result["available"] is True
    assert result["coverage_percent"] == payload["coverage_percent"]
    assert result["breakdown"] == payload["breakdown"]


def test_ac_score_water_line_defaults_to_empty_on_missing_baseline(
    tmp_path: Path,
) -> None:
    result = eb.ac_score_water_line(tmp_path)
    assert result == {"baselined_ac_count": 0, "mean_floor_score": None}


def test_ac_score_water_line_computes_count_and_mean(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "docs" / "ssot"
    baseline_dir.mkdir(parents=True)
    lines = [
        json.dumps({"ac_id": "AC-x.1", "score": 0.8, "metric": "m", "provenance": "p"}),
        json.dumps({"ac_id": "AC-x.2", "score": 1.0, "metric": "m", "provenance": "p"}),
    ]
    (baseline_dir / "ac-score-baseline.jsonl").write_text("\n".join(lines) + "\n")
    result = eb.ac_score_water_line(tmp_path)
    assert result["baselined_ac_count"] == 2
    assert result["mean_floor_score"] == pytest.approx(0.9)


def test_ac_tier_water_line_defaults_to_zero_on_missing_baseline(
    tmp_path: Path,
) -> None:
    result = eb.ac_tier_water_line(tmp_path)
    assert result == {"untagged_debt_count": 0}


def test_ac_tier_water_line_counts_the_untagged_set(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "docs" / "ssot"
    baseline_dir.mkdir(parents=True)
    payload = {"untagged": ["AC-x.1", "AC-x.2", "AC-x.3"]}
    (baseline_dir / "ac-tier-baseline.json").write_text(json.dumps(payload))
    result = eb.ac_tier_water_line(tmp_path)
    assert result["untagged_debt_count"] == len(payload["untagged"])


def test_protection_water_line_defaults_to_all_zero_on_missing_floor(
    tmp_path: Path,
) -> None:
    result = eb.protection_water_line(tmp_path)
    assert result["floor"] == {
        "has_real_ref": 0,
        "has_proof": 0,
        "has_score": 0,
        "has_mirror": 0,
    }


def test_protection_water_line_reads_the_committed_floor(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "docs" / "ssot"
    baseline_dir.mkdir(parents=True)
    payload = {
        "version": 1,
        "floor": {"has_real_ref": 5, "has_proof": 3, "has_score": 1, "has_mirror": 2},
    }
    (baseline_dir / "protection-floor.json").write_text(json.dumps(payload))
    result = eb.protection_water_line(tmp_path)
    assert result["floor"] == payload["floor"]


def test_cassette_eval_water_line_reads_the_real_committed_corpus() -> None:
    """No tmp_path isolation: cassette_graded_eval.evaluate()'s ground-truth and
    cassette dirs are not parameterizable by repo_root — this always reads the
    real, committed corpus (#1681's graded-eval), which is the correct behavior
    for a bundle that must report the ACTUAL corpus accuracy, not a synthetic one."""
    result = eb.cassette_eval_water_line()
    assert result["case_count"] > 0
    assert result["corpus_count_floor"] > 0
    assert result["mean_field_accuracy"] is not None
    assert 0.0 <= result["mean_field_accuracy"] <= 1.0
    assert result["regressions"] == 0
    assert result["missing"] == 0


# --------------------------------------------------------------------------- #
# AC8.13.164 — bundle assembly
# --------------------------------------------------------------------------- #
def test_AC8_13_164_bundle_assembles_the_four_ratchet_water_lines_and_gate_map(
    tmp_path: Path,
) -> None:
    """AC8.13.164: build_evidence_bundle assembles the gate map, all four
    ratchet water-lines, and corpus per-field accuracy from already-computed
    artifacts — never re-running the gates that produced them."""
    bundle = eb.build_evidence_bundle(tmp_path)

    assert bundle["version"] == eb.BUNDLE_VERSION
    assert bundle["gate_map"] == [dict(entry) for entry in eb.GATE_MAP]
    assert set(bundle["ratchets"]) == {"coverage", "ac_score", "ac_tier", "protection"}
    # tmp_path has none of the baseline files -> every ratchet reads its
    # documented "missing" default (proves the reader is wired, not stubbed).
    assert bundle["ratchets"]["coverage"] == {"available": False}
    assert bundle["ratchets"]["ac_tier"] == {"untagged_debt_count": 0}
    # cassette_eval always reads the real corpus regardless of repo_root.
    assert bundle["cassette_eval"]["case_count"] > 0
    assert bundle["provider_health"] is None


def test_build_evidence_bundle_carries_gate_results_and_provider_health(
    tmp_path: Path,
) -> None:
    bundle = eb.build_evidence_bundle(
        tmp_path,
        gate_results={"unified-coverage": "success"},
        provider_health={"ai_ocr_status": "passed"},
    )
    assert bundle["gate_results"] == {"unified-coverage": "success"}
    assert bundle["provider_health"] == {"ai_ocr_status": "passed"}


def test_build_evidence_bundle_defaults_are_empty_not_none_for_gate_results(
    tmp_path: Path,
) -> None:
    bundle = eb.build_evidence_bundle(tmp_path)
    assert bundle["gate_results"] == {}


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #
def test_render_markdown_includes_every_gate_map_row(tmp_path: Path) -> None:
    lint_result = "success"
    bundle = eb.build_evidence_bundle(tmp_path, gate_results={"lint": lint_result})
    rendered = eb.render_markdown(bundle)
    for entry in bundle["gate_map"]:
        assert entry["job"] in rendered
        assert entry["lane"] in rendered
    assert lint_result in rendered


def test_render_markdown_reports_provider_health_unavailability_when_absent(
    tmp_path: Path,
) -> None:
    bundle = eb.build_evidence_bundle(tmp_path)
    rendered = eb.render_markdown(bundle)
    availability_marker = "Not available"
    assert availability_marker in rendered


def test_render_markdown_includes_provider_health_when_present(
    tmp_path: Path,
) -> None:
    bundle = eb.build_evidence_bundle(
        tmp_path, provider_health={"ai_ocr_status": "regression-failed"}
    )
    rendered = eb.render_markdown(bundle)
    status_value = bundle["provider_health"]["ai_ocr_status"]
    assert status_value in rendered


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_main_writes_json_output_and_appends_the_github_summary(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence-bundle.json"
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("existing content\n")

    exit_code = eb.main(
        [
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output_path),
            "--github-summary",
            str(summary_path),
        ]
    )

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["version"] == eb.BUNDLE_VERSION
    summary_text = summary_path.read_text(encoding="utf-8")
    assert summary_text.startswith("existing content\n")
    assert len(summary_text) > len("existing content\n")


def test_main_parses_gate_results_and_provider_status(tmp_path: Path) -> None:
    output_path = tmp_path / "evidence-bundle.json"
    exit_code = eb.main(
        [
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output_path),
            "--gate-results",
            json.dumps({"lint": "success"}),
            "--provider-status",
            "passed",
            "--provider-exit-code",
            "0",
        ]
    )
    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["gate_results"] == {"lint": "success"}
    assert written["provider_health"]["ai_ocr_status"] == "passed"
    assert written["provider_health"]["ai_ocr_exit_code"] == "0"


def test_main_omits_provider_health_when_provider_status_not_given(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence-bundle.json"
    exit_code = eb.main(["--repo-root", str(tmp_path), "--output", str(output_path)])
    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["provider_health"] is None


# --------------------------------------------------------------------------- #
# AC8.13.165 — both real producers wire the same generator in
# --------------------------------------------------------------------------- #
def test_AC8_13_165_both_producers_wire_the_same_generator_into_their_workflow() -> (
    None
):
    """AC8.13.165: main-CI (after unified-coverage + ac-behavioral-ratchet) and
    the nightly audit-replay both call tools/generate_evidence_bundle.py and
    upload an `evidence-bundle` artifact; only audit-replay supplies
    --provider-status/--provider-exit-code."""
    generator_script = "tools/generate_evidence_bundle.py"
    artifact_name = "evidence-bundle"

    ci_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    )
    ci_job = ci_workflow["jobs"]["evidence-bundle"]
    assert set(ci_job["needs"]) == {
        "changes",
        "unified-coverage",
        "ac-behavioral-ratchet",
    }
    ci_commands = "\n".join(
        str(step.get("run", "")) for step in ci_job["steps"] if isinstance(step, dict)
    )
    assert generator_script in ci_commands
    provider_flag = "--provider-status"
    assert provider_flag not in ci_commands
    assert_pyyaml_installed_before_generator(ci_commands, generator_script)

    audit_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "audit-replay.yml").read_text()
    )
    audit_job = audit_workflow["jobs"]["evidence-bundle"]
    assert audit_job["needs"] == ["audit-replay"]
    audit_commands = "\n".join(
        str(step.get("run", ""))
        for step in audit_job["steps"]
        if isinstance(step, dict)
    )
    assert generator_script in audit_commands
    assert provider_flag in audit_commands
    assert_pyyaml_installed_before_generator(audit_commands, generator_script)

    for workflow in (ci_workflow, audit_workflow):
        job = workflow["jobs"]["evidence-bundle"]
        upload_step = next(
            step
            for step in job["steps"]
            if isinstance(step, dict) and "upload-artifact" in str(step.get("uses", ""))
        )
        assert upload_step["with"]["name"] == artifact_name


def test_evidence_bundle_ci_job_is_not_required_by_finish() -> None:
    """#1690: evidence-bundle is informational — it must never become a
    required check (constraint carried over from #1689's cost-right work)."""
    ci_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    )
    finish_needs = ci_workflow["jobs"]["finish"]["needs"]
    evidence_bundle_job_id = "evidence-bundle"
    assert evidence_bundle_job_id not in finish_needs


# --------------------------------------------------------------------------- #
# Gate map drift: every ci.yml-hosted GATE_MAP entry must name a real job.
# --------------------------------------------------------------------------- #
def test_gate_map_job_ids_exist_in_the_live_ci_workflow() -> None:
    ci_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    )
    live_jobs = ci_workflow["jobs"]
    for entry in eb.GATE_MAP:
        assert entry["job"] in live_jobs, entry["job"]


def test_gate_map_has_no_duplicate_job_entries() -> None:
    jobs = [entry["job"] for entry in eb.GATE_MAP]
    assert len(jobs) == len(set(jobs))
