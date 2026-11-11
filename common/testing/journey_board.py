#!/usr/bin/env python3
"""Core-journey board: one stdlib-only record per staging lane run (#2370)."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

SCHEMA_VERSION = 1
CHECKPOINT_PROPERTY_PREFIX = "checkpoint."
CHECKPOINT_REACHED = "reached"

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_MAP_PATH = REPO_ROOT / "common/testing/data/core-journey-checkpoints.json"

ARTIFACT_NAME = "staging-ai-ocr-test-context"
GATE_XML = "staging-ai-ocr-gate.xml"
RETRY_XML = "staging-ai-ocr-retry.xml"
CONTEXT_FILE = "staging-ai-ocr-context.txt"
MANIFEST_FILE = "staging-ai-ocr-manifest.json"
GATE_JOB_NAME = "Staging AI/OCR Gate"
GATE_JOB_SUFFIX = f" / {GATE_JOB_NAME}"
DEPLOY_STAGING_JOB = "Deploy Staging"
DEPLOY_WORKFLOW = ".github/workflows/deploy.yml"
REPLAY_WORKFLOW = ".github/workflows/audit-replay.yml"
BOARD_WORKFLOWS = (DEPLOY_WORKFLOW, REPLAY_WORKFLOW)
LANES = ("canary", "core_journey", "audit_replay", "all")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

INDEX_CAP = 200
MATRIX_COLUMNS = 10
AUDIT_REPLAY_STALE_DAYS = 8

CHECKPOINT_STATUS_ORDER = (
    "failed",
    "unproven",
    "blocked",
    "skipped",
    "passed",
    "invalidated",
    "not-run",
    "not-covered",
)
PASSED_OUTCOMES = ("passed", "passed-on-retry")
FAILED_OUTCOMES = ("failed", "error")


@dataclass(frozen=True)
class Checkpoint:
    id: str
    title: str
    gap: str | None = None


@dataclass(frozen=True)
class Proof:
    test: str
    file: str
    reaches: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointMap:
    checkpoints: tuple[Checkpoint, ...]
    proofs: tuple[Proof, ...]


@dataclass
class Case:
    test_id: str
    outcome: str
    seconds: float
    reached: list[str] = field(default_factory=list)
    failure_class: str | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_checkpoint_map(path: Path = CHECKPOINT_MAP_PATH) -> CheckpointMap:
    """Load the checkpoint map and reject unknown or duplicate checkpoint ids."""
    data = _load_json(path)
    checkpoints = tuple(
        Checkpoint(id=item["id"], title=item["title"], gap=item.get("gap"))
        for item in data["checkpoints"]
    )
    known = {checkpoint.id for checkpoint in checkpoints}
    proofs = tuple(
        Proof(test=item["test"], file=item["file"], reaches=tuple(item["reaches"]))
        for item in data["proofs"]
    )
    for proof in proofs:
        unknown = sorted(set(proof.reaches) - known)
        if unknown:
            raise ValueError(f"{proof.test} reaches unknown checkpoints {unknown}")
        if len(set(proof.reaches)) != len(proof.reaches):
            raise ValueError(f"{proof.test} lists a checkpoint more than one time")
    return CheckpointMap(checkpoints=checkpoints, proofs=proofs)


def _case_outcome(case: ET.Element) -> str:
    for tag, outcome in (
        ("failure", "failed"),
        ("error", "error"),
        ("skipped", "skipped"),
    ):
        if case.find(tag) is not None:
            return outcome
    return "passed"


def normalize_test_id(test_id: str) -> str:
    """Drop a trailing parametrize suffix such as '[chromium]'."""
    return re.sub(r"\[[^\]]*\]$", "", test_id)


def parse_junit(path: Path) -> list[Case]:
    """Read one JUnit XML file into cases with their reached checkpoints."""
    cases: list[Case] = []
    for element in ET.parse(path).getroot().iter("testcase"):
        classname = element.get("classname", "")
        name = element.get("name", "<unknown>")
        reached = [
            prop.get("name", "")[len(CHECKPOINT_PROPERTY_PREFIX) :]
            for prop in element.iter("property")
            if prop.get("name", "").startswith(CHECKPOINT_PROPERTY_PREFIX)
            and prop.get("value") == CHECKPOINT_REACHED
        ]
        cases.append(
            Case(
                test_id=normalize_test_id(
                    f"{classname}::{name}" if classname else name
                ),
                outcome=_case_outcome(element),
                seconds=round(float(element.get("time") or 0.0), 2),
                reached=reached,
            )
        )
    return cases


def merge_retry(first: list[Case], retry: list[Case]) -> list[Case]:
    """Apply the gate's single transient retry to the first-pass cases."""
    retried = {case.test_id: case for case in retry}
    merged: list[Case] = []
    for case in first:
        again = retried.get(case.test_id)
        if again is None or (
            again.outcome not in FAILED_OUTCOMES and case.outcome not in FAILED_OUTCOMES
        ):
            merged.append(case)
        elif again.outcome in FAILED_OUTCOMES or again.outcome != "passed":
            merged.append(again)
        else:
            merged.append(
                Case(
                    case.test_id, "passed-on-retry", again.seconds, list(again.reached)
                )
            )
    return merged


def proof_checkpoint_statuses(case: Case | None, proof: Proof) -> dict[str, str]:
    """Compute the status of each checkpoint covered by one proof."""
    if case is None:
        return dict.fromkeys(proof.reaches, "not-run")
    if case.outcome == "skipped":
        return dict.fromkeys(proof.reaches, "skipped")
    if case.outcome in PASSED_OUTCOMES:
        return {
            cp: "passed" if cp in case.reached else "unproven" for cp in proof.reaches
        }
    statuses: dict[str, str] = {}
    failure_seen = False
    for cp in proof.reaches:
        if cp in case.reached:
            statuses[cp] = "passed"
        elif not failure_seen:
            statuses[cp] = "failed"
            failure_seen = True
        else:
            statuses[cp] = "blocked"
    return statuses


def worst(statuses: list[str]) -> str:
    return min(statuses, key=CHECKPOINT_STATUS_ORDER.index)


def rollup_checkpoints(
    cases: list[Case], checkpoint_map: CheckpointMap
) -> dict[str, dict[str, Any]]:
    by_id = {case.test_id: case for case in cases}
    per_proof = {
        proof.test: proof_checkpoint_statuses(by_id.get(proof.test), proof)
        for proof in checkpoint_map.proofs
    }
    rollup: dict[str, dict[str, Any]] = {}
    for cp in checkpoint_map.checkpoints:
        proofs = [
            {"test": proof.test, "status": per_proof[proof.test][cp.id]}
            for proof in checkpoint_map.proofs
            if cp.id in proof.reaches
        ]
        rollup[cp.id] = (
            {"status": worst([p["status"] for p in proofs]), "proofs": proofs}
            if proofs
            else {"status": "not-covered", "gap": cp.gap}
        )
    return rollup


def parse_context(path: Path) -> dict[str, str]:
    context: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key and " " not in key:
            context[key.strip()] = value.strip()
    return context


def _find(artifact_dir: Path, name: str) -> Path | None:
    matches = sorted(artifact_dir.rglob(name)) if artifact_dir.is_dir() else []
    return matches[0] if matches else None


def _run_meta(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(run.get("id", "")),
        "attempt": int(run.get("run_attempt") or 1),
        "url": run.get("html_url", ""),
        "workflow": run.get("path", ""),
        "event": run.get("event", ""),
        "conclusion": run.get("conclusion"),
        "completed_at": run.get("updated_at") or run.get("run_started_at") or "",
    }


def _lane_from_run(run: dict[str, Any]) -> str:
    if run.get("path") == DEPLOY_WORKFLOW:
        return "canary"
    match = re.search(
        r"\((core_journey|audit_replay|canary|all)\)", run.get("display_title", "")
    )
    return match.group(1) if match else "audit_replay"


def _counts(cases: list[Case]) -> dict[str, int]:
    return {
        "total": len(cases),
        "passed": sum(case.outcome in PASSED_OUTCOMES for case in cases),
        "failed": sum(case.outcome in FAILED_OUTCOMES for case in cases),
        "skipped": sum(case.outcome == "skipped" for case in cases),
    }


def _valid_sha(value: str | None) -> str | None:
    return value if value and SHA_PATTERN.match(value) else None


def _is_gate_job(name: str) -> bool:
    return name == GATE_JOB_NAME or name.endswith(GATE_JOB_SUFFIX)


def build_record(
    artifact_dir: Path,
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    checkpoint_map: CheckpointMap,
    *,
    resolved_sha: str | None = None,
    recorded_at: str | None = None,
    map_note: str | None = None,
) -> dict[str, Any] | None:
    """Build the record for one gate run, or None when nothing applies."""
    if run.get("path") not in BOARD_WORKFLOWS:
        raise ValueError(
            f"run {run.get('id')} is not a {' or '.join(BOARD_WORKFLOWS)} run"
        )
    ran = [
        job
        for job in jobs
        if _is_gate_job(job.get("name", ""))
        and job.get("conclusion") not in (None, "skipped")
    ]
    deploy_jobs = [
        job
        for job in jobs
        if job.get("name") == DEPLOY_STAGING_JOB
        and job.get("conclusion") not in (None, "skipped")
    ]
    meta = _run_meta(run)
    recorded_at = recorded_at or datetime.now(UTC).isoformat(timespec="seconds")
    context_path = _find(artifact_dir, CONTEXT_FILE)
    if context_path is None:
        if run.get("path") == DEPLOY_WORKFLOW and not ran and not deploy_jobs:
            return None
        if ran:
            status, reason = "no-evidence", "the gate ran but uploaded no test context"
        elif deploy_jobs:
            status = "not-run"
            reason = (
                "the staging AI/OCR gate job did not run "
                f"(Deploy Staging concluded {deploy_jobs[0].get('conclusion')})"
            )
        else:
            status, reason = "not-run", "the staging AI/OCR gate job did not run"
        return _record(
            lane=_lane_from_run(run),
            status=status,
            reason=reason,
            tested_sha=_valid_sha(resolved_sha),
            expected_version=None,
            meta=meta,
            cases=[],
            junit=False,
            checkpoint_map=checkpoint_map,
            recorded_at=recorded_at,
            map_note=map_note,
        )
    context = parse_context(context_path)
    lane = context.get("corpus") or _lane_from_run(run)
    if lane not in LANES:
        raise ValueError(f"unknown lane {lane!r}; expected one of {LANES}")
    gate_xml = _find(artifact_dir, GATE_XML)
    cases = parse_junit(gate_xml) if gate_xml else []
    retry_xml = _find(artifact_dir, RETRY_XML)
    if retry_xml:
        cases = merge_retry(cases, parse_junit(retry_xml))
    manifest_path = _find(artifact_dir, MANIFEST_FILE)
    if manifest_path:
        classes = {
            normalize_test_id(item["test"]): item.get("subtype") or item.get("class")
            for item in _load_json(manifest_path).get("cases", [])
        }
        for case in cases:
            if case.outcome in FAILED_OUTCOMES:
                case.failure_class = classes.get(case.test_id)
    record = _record(
        lane=lane,
        status=context.get("ai_ocr_outcome", "not-run"),
        reason=None if gate_xml else "the gate wrote no JUnit file",
        tested_sha=_valid_sha(context.get("tested_sha")) or _valid_sha(resolved_sha),
        expected_version=context.get("expected_version"),
        meta=meta,
        cases=cases,
        junit=gate_xml is not None,
        checkpoint_map=checkpoint_map,
        recorded_at=recorded_at,
        map_note=map_note,
    )
    drift = staging_drift(context.get("expected_version"), context.get("end_version"))
    if drift:
        invalidate(record, drift)
    return record


def invalidate(record: dict[str, Any], reason: str) -> None:
    """Mark a record invalidated when staging changed mid-run."""
    record["original_status"] = record["status"]
    record["status"], record["reason"] = "invalidated", reason
    for cell in record["checkpoints"].values():
        if cell["status"] != "not-covered":
            cell["original"] = cell["status"]
            cell["status"] = "invalidated"


def staging_drift(expected: str | None, end: str | None) -> str | None:
    """Name a staging release-tag change during the run, or return None."""
    if (
        not expected
        or not end
        or not (expected.startswith("v") and end.startswith("v"))
        or expected == end
    ):
        return None
    return f"staging changed from {expected} to {end} during the run"


def _record(
    *,
    lane: str,
    status: str,
    reason: str | None,
    tested_sha: str | None,
    expected_version: str | None,
    meta: dict[str, Any],
    cases: list[Case],
    junit: bool,
    checkpoint_map: CheckpointMap,
    recorded_at: str,
    map_note: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "lane": lane,
        "status": status,
        "reason": reason,
        "tested_sha": tested_sha,
        "expected_version": expected_version,
        "recorded_at": recorded_at,
        "junit": junit,
        "map_note": map_note,
        "run": meta,
        "counts": _counts(cases),
        "tests": [
            {
                "test": case.test_id,
                "outcome": case.outcome,
                "seconds": case.seconds,
                "failure_class": case.failure_class,
            }
            for case in cases
        ],
        "checkpoints": rollup_checkpoints(cases, checkpoint_map),
    }


def record_path(board_dir: Path, record: dict[str, Any]) -> Path:
    run = record["run"]
    return (
        board_dir
        / "records"
        / (record["tested_sha"] or "unknown")
        / f"{record['lane']}-{run['id']}-{run['attempt']}.json"
    )


def _preference(record: dict[str, Any]) -> tuple[bool, str]:
    return (record.get("tested_sha") is not None, record.get("recorded_at") or "")


def load_records(board_dir: Path) -> list[dict[str, Any]]:
    """Read every record, keeping the preferred record per run attempt."""
    by_run: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted((board_dir / "records").rglob("*.json")):
        record = _load_json(path)
        if record.get("schema") != SCHEMA_VERSION:
            continue
        key = (record["run"]["id"], record["run"]["attempt"])
        current = by_run.get(key)
        if current is None or _preference(record) > _preference(current):
            by_run[key] = record
    return sorted(by_run.values(), key=lambda r: r["run"]["completed_at"], reverse=True)


def build_index(
    records: list[dict[str, Any]], checkpoint_map: CheckpointMap, *, generated_at: str
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": generated_at,
        "checkpoints": [
            {"id": cp.id, "title": cp.title, "gap": cp.gap}
            for cp in checkpoint_map.checkpoints
        ],
        "records": records[:INDEX_CAP],
    }


def latest_by_lane(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest.setdefault(record["lane"], record)
    return latest


def combine_for_sha(
    records: list[dict[str, Any]], sha: str
) -> dict[str, dict[str, Any]]:
    """Combine the newest record of each lane for one tested SHA, worst status first."""
    lanes = latest_by_lane([r for r in records if r["tested_sha"] == sha])
    combined: dict[str, dict[str, Any]] = {}
    for lane_record in lanes.values():
        for cp_id, cell in lane_record["checkpoints"].items():
            current = combined.get(cp_id)
            if current is None or CHECKPOINT_STATUS_ORDER.index(
                cell["status"]
            ) < CHECKPOINT_STATUS_ORDER.index(current["status"]):
                combined[cp_id] = {
                    "status": cell["status"],
                    "lane": lane_record["lane"],
                    "url": lane_record["run"]["url"],
                    "gap": cell.get("gap"),
                }
    return combined


def stale_reason(
    record: dict[str, Any], latest: dict[str, dict[str, Any]]
) -> str | None:
    canary = latest.get("canary")
    if (
        record["lane"] == "core_journey"
        and canary is not None
        and canary["tested_sha"]
        and record["tested_sha"] != canary["tested_sha"]
    ):
        return "did not test the newest staging deploy"
    return None


def _status_class(status: str) -> str:
    if status in PASSED_OUTCOMES:
        return "ok"
    if status in ("not-run", "not-covered", "skipped", "invalidated"):
        return "none"
    return "bad"


def _lane_class(record: dict[str, Any]) -> str:
    if record["status"] == "passed" and not (
        record.get("junit")
        and record["counts"]["passed"] > 0
        and record["counts"]["failed"] == 0
    ):
        return "bad"
    return _status_class(record["status"])


def _lane_label(record: dict[str, Any]) -> str:
    label = record["status"]
    if record["status"] == "passed" and _lane_class(record) == "bad":
        label += " (no test evidence)"
    if record["reason"]:
        label += f" ({record['reason']})"
    if record.get("map_note"):
        label += f" ({record['map_note']})"
    return label


def _short(sha: str | None) -> str:
    return escape(sha[:8]) if sha else "unknown"


def _sha_versions(records: list[dict[str, Any]]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for record in records:
        sha = record.get("tested_sha")
        version = record.get("expected_version")
        if sha and version and sha not in versions:
            versions[sha] = version
    return versions


def _counts_summary(counts: dict[str, int]) -> str:
    return (
        f"{counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['skipped']} skipped"
    )


def _kpi_card(cls: str, label: str, value: str, sub: str) -> str:
    return (
        f'<div class="kpi-card {cls}"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>'
    )


def _render_kpi_strip(
    index: dict[str, Any],
    latest: dict[str, dict[str, Any]],
    combined: dict[str, dict[str, Any]],
    shas: list[str],
    versions: dict[str, str],
) -> str:
    primary = (
        latest.get("canary")
        or latest.get("core_journey")
        or next(iter(latest.values()))
    )
    cand_ver = escape(
        primary.get("expected_version")
        or versions.get(primary.get("tested_sha") or "", "")
        or "untagged"
    )
    head_sha = shas[0] if shas else None
    head_cells = combined.get(head_sha, {}) if head_sha else {}
    total_cp = len(index["checkpoints"])
    passed_cp = sum(
        1
        for cp in index["checkpoints"]
        if head_cells.get(cp["id"], {}).get("status") in PASSED_OUTCOMES
    )
    failed_cp = sum(
        1
        for cp in index["checkpoints"]
        if head_cells.get(cp["id"], {}).get("status")
        in ("failed", "unproven", "blocked")
    )
    cp_class = (
        "bad"
        if failed_cp > 0
        else ("ok" if passed_cp == total_cp and total_cp > 0 else "none")
    )
    replay = latest.get("audit_replay")
    replay_status, replay_sha, replay_class = (
        (
            escape(_lane_label(replay)),
            _short(replay.get("tested_sha")),
            _lane_class(replay),
        )
        if replay is not None
        else ("no record", "—", "none")
    )
    return (
        '<div class="kpi-grid">'
        + _kpi_card(
            _lane_class(primary),
            "Staging Candidate",
            cand_ver,
            f"SHA <code>{_short(primary.get('tested_sha'))}</code>",
        )
        + _kpi_card(
            cp_class,
            "Head Checkpoint Coverage",
            f"{passed_cp} / {total_cp}",
            f"{failed_cp} failed or blocked on <code>{_short(head_sha)}</code>",
        )
        + _kpi_card(
            replay_class,
            "Newest Audit Replay",
            replay_status,
            f"SHA <code>{replay_sha}</code>",
        )
        + "</div>"
    )


def render_fragment(index: dict[str, Any]) -> str:
    """Render the board as an HTML fragment."""
    records = index["records"]
    gen_ts = escape(index["generated_at"])
    parts = [
        f'<p class="generated">Board generated <time data-ts="{gen_ts}">{gen_ts}</time>. '
        "Records hold outcomes only. The board blocks nothing.</p>"
    ]
    if not records:
        parts.append('<p class="bad">No lane run has published a record yet.</p>')
        return "\n".join(parts)

    latest = latest_by_lane(records)
    versions = _sha_versions(records)
    shas = list(dict.fromkeys(r["tested_sha"] for r in records if r["tested_sha"]))[
        :MATRIX_COLUMNS
    ]
    combined = {sha: combine_for_sha(records, sha) for sha in shas}

    parts.append(_render_kpi_strip(index, latest, combined, shas, versions))
    parts.append("<h2>Latest run per lane</h2>")
    parts.append(
        "<table><thead><tr><th>Lane</th><th>Status</th><th>Tested SHA</th>"
        "<th>Version</th><th>Completed</th><th>Tests</th></tr></thead><tbody>"
    )
    for lane, record in sorted(latest.items()):
        stale_days = AUDIT_REPLAY_STALE_DAYS if lane == "audit_replay" else ""
        stale = stale_reason(record, latest)
        version = record["expected_version"] or versions.get(
            record["tested_sha"] or "", ""
        )
        comp = escape(record["run"]["completed_at"])
        parts.append(
            "<tr>"
            f"<td><code>{escape(lane)}</code></td>"
            f'<td class="{_lane_class(record)}"><a href="{escape(record["run"]["url"])}">{escape(_lane_label(record))}</a></td>'
            f"<td><code>{_short(record['tested_sha'])}</code></td>"
            f"<td>{escape(version)}</td>"
            f'<td><time data-ts="{comp}" data-stale-days="{stale_days}">{comp}</time>'
            + (f' <span class="bad">STALE: {escape(stale)}</span>' if stale else "")
            + f"</td><td>{_counts_summary(record['counts'])}</td></tr>"
        )
    parts.append("</tbody></table>")

    parts.append("<h2>Core journey checkpoints by tested SHA</h2>")
    header = "".join(
        f"<th><code>{_short(sha)}</code>"
        + (
            f' <span class="ver-badge">{escape(versions[sha])}</span>'
            if sha in versions
            else ""
        )
        + "</th>"
        for sha in shas
    )
    parts.append(f"<table><thead><tr><th>Checkpoint</th>{header}</tr></thead><tbody>")
    for cp in index["checkpoints"]:
        cells = []
        for sha in shas:
            cell = combined[sha].get(cp["id"])
            if cell is None:
                cells.append('<td class="none">not-run</td>')
            elif cell["status"] == "not-covered":
                cells.append(
                    f'<td class="none">{escape(cell["status"])} {escape(cell.get("gap") or "")}</td>'
                )
            else:
                cells.append(
                    f'<td class="{_status_class(cell["status"])}">'
                    f'<a href="{escape(cell["url"])}">{escape(cell["status"])}</a> ({escape(cell["lane"])})</td>'
                )
        parts.append(
            f"<tr><th>{escape(cp['id'])} {escape(cp['title'])}</th>{''.join(cells)}</tr>"
        )
    parts.append("</tbody></table>")

    parts.append("<h2>Tests in the latest run per lane</h2>")
    for lane, record in sorted(latest.items()):
        ver = record["expected_version"] or versions.get(record["tested_sha"] or "", "")
        ver_suffix = f" ({escape(ver)})" if ver else ""
        parts.append(
            f"<h3>{escape(lane)} · {_short(record['tested_sha'])}{ver_suffix}</h3>"
        )
        if not record["tests"]:
            parts.append(
                f'<p class="none">No test ran: {escape(record["reason"] or record["status"])}</p>'
            )
            continue
        parts.append('<ul class="test-list">')
        for test in record["tests"]:
            detail = (
                f" [{escape(test['failure_class'])}]" if test["failure_class"] else ""
            )
            seconds = test.get("seconds")
            timing = (
                f' <span class="test-time">({seconds:.2f}s)</span>'
                if isinstance(seconds, (int, float))
                else ""
            )
            parts.append(
                f'<li class="{_status_class(test["outcome"])}">{escape(test["outcome"])}: '
                f"<code>{escape(test['test'])}</code>{detail}{timing}</li>"
            )
        parts.append("</ul>")
    return "\n".join(parts)


def _age_days(completed_at: str, now: datetime) -> float | None:
    try:
        return (
            now - datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        ).total_seconds() / 86400
    except ValueError:
        return None


def checkpoint_map_has_proof(checkpoint_map: CheckpointMap, checkpoint_id: str) -> bool:
    return any(checkpoint_id in proof.reaches for proof in checkpoint_map.proofs)


def render_release_row(
    records: list[dict[str, Any]],
    checkpoint_map: CheckpointMap,
    *,
    sha: str | None,
    version_ref: str,
    now: datetime,
    board_available: bool = True,
) -> str:
    """Markdown board row for one release (#2370)."""
    lines = [
        f"### Core journey board: {version_ref} ({sha[:8] if sha else 'unresolved'})",
        "",
    ]
    if not sha:
        lines.append("Board unavailable: the release SHA could not be resolved.")
        return "\n".join(lines)
    if not board_available:
        lines.append(
            "Board unavailable: no board records could be read from gh-pages. "
            "This is not evidence about the release."
        )
        return "\n".join(lines)
    lines += ["| Lane | Status | Completed | Tests | Run |", "|---|---|---|---|---|"]
    for lane in LANES:
        record = next(
            (r for r in records if r["lane"] == lane and r["tested_sha"] == sha), None
        )
        if record is None:
            lines.append(f"| {lane} | NO RECORD for this revision | | | |")
        else:
            lines.append(
                f"| {lane} | {_lane_label(record)} | {record['run']['completed_at']} | "
                f"{_counts_summary(record['counts'])} | {record['run']['url']} |"
            )
    combined = combine_for_sha(records, sha)
    lines += ["", "| Checkpoint | Status |", "|---|---|"]
    known = {cp.id for cp in checkpoint_map.checkpoints}
    extra = [
        Checkpoint(cp_id, "(not in the current checkpoint map)")
        for cp_id in sorted(set(combined) - known)
    ]
    for cp in [*checkpoint_map.checkpoints, *extra]:
        cell = combined.get(cp.id)
        if cell is None:
            label = (
                "not-run"
                if checkpoint_map_has_proof(checkpoint_map, cp.id)
                else f"not-covered {cp.gap or ''}".strip()
            )
        else:
            label = cell["status"] + (f" {cell['gap']}" if cell.get("gap") else "")
        lines.append(f"| {cp.id} {cp.title} | {label} |")
    replay = next((r for r in records if r["lane"] == "audit_replay"), None)
    lines.append("")
    if replay is None:
        lines.append("Newest audit replay: none recorded.")
    else:
        age = _age_days(replay["run"]["completed_at"], now)
        stale = age is not None and age > AUDIT_REPLAY_STALE_DAYS
        age_text = "unknown age" if age is None else f"{age:.1f} days old"
        lines.append(
            f"Newest audit replay: {_lane_label(replay)} on {(replay['tested_sha'] or 'unknown')[:8]}, "
            f"{age_text}{' (STALE)' if stale else ''}."
        )
    lines += ["", "The board blocks nothing. Read it before you approve this release."]
    return "\n".join(lines)


def pick_artifact(
    artifacts: list[dict[str, Any]], run: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the gate artifact created at or after the current attempt started."""
    started = run.get("run_started_at") or ""
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == ARTIFACT_NAME
        and not artifact.get("expired")
        and (artifact.get("created_at") or "") >= started
    ]
    return max(candidates, key=lambda artifact: artifact["created_at"], default=None)


def map_for_tested_revision(path: Path | None) -> tuple[CheckpointMap, str | None]:
    """Use the checkpoint map of the tested revision, or drop proofs when absent."""
    current = load_checkpoint_map()
    if path is None:
        return current, None
    if not path.is_file():
        return (
            CheckpointMap(checkpoints=current.checkpoints, proofs=()),
            "the tested revision has no checkpoint map",
        )
    return load_checkpoint_map(path), None


def _cmd_build_record(args: argparse.Namespace) -> int:
    run = _load_json(args.run_json)
    jobs_payload = _load_json(args.jobs_json)
    jobs = (
        jobs_payload.get("jobs", jobs_payload)
        if isinstance(jobs_payload, dict)
        else jobs_payload
    )
    head_repository = (run.get("head_repository") or {}).get("full_name")
    if head_repository != args.repository:
        print(
            f"error: run {run.get('id')} belongs to {head_repository}, not {args.repository}"
        )
        return 2
    checkpoint_map, map_note = map_for_tested_revision(args.checkpoint_map)
    try:
        record = build_record(
            args.artifact_dir,
            run,
            jobs,
            checkpoint_map,
            resolved_sha=args.resolved_sha or None,
            map_note=map_note,
        )
    except ValueError as error:
        print(f"error: {error}")
        return 2
    if record is None:
        print("no-record: the run has no staging deploy and no staging AI/OCR gate job")
        return 0
    target = record_path(args.board_dir, record)
    _write_json(target, record)
    print(f"record: {target}")
    return 0


def _cmd_pick_artifact(args: argparse.Namespace) -> int:
    payload = _load_json(args.artifacts_json)
    artifacts = (
        payload.get("artifacts", payload) if isinstance(payload, dict) else payload
    )
    artifact = pick_artifact(artifacts, _load_json(args.run_json))
    print(artifact["id"] if artifact else "")
    return 0


def _cmd_build_index(args: argparse.Namespace) -> int:
    records = load_records(args.board_dir)
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    index = build_index(records, load_checkpoint_map(), generated_at=generated_at)
    _write_json(args.board_dir / "index.json", index)
    (args.board_dir / "fragment.html").write_text(
        render_fragment(index) + "\n", encoding="utf-8"
    )
    print(f"index: {len(index['records'])} records")
    return 0


def _cmd_release_row(args: argparse.Namespace) -> int:
    try:
        available = (args.board_dir / "records").is_dir()
        text = render_release_row(
            load_records(args.board_dir) if available else [],
            load_checkpoint_map(),
            sha=_valid_sha(args.sha),
            version_ref=args.version_ref,
            now=datetime.now(UTC),
            board_available=available,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        text = (
            f"### Core journey board: {args.version_ref}\n\nBoard unavailable: {error}"
        )
    print(text)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("build-record", help="build the record of one gate run")
    record.add_argument("--artifact-dir", type=Path, required=True)
    record.add_argument("--run-json", type=Path, required=True)
    record.add_argument("--jobs-json", type=Path, required=True)
    record.add_argument("--board-dir", type=Path, required=True)
    record.add_argument("--resolved-sha", default="")
    record.add_argument("--repository", required=True)
    record.add_argument("--checkpoint-map", type=Path, default=None)
    record.set_defaults(func=_cmd_build_record)
    pick = sub.add_parser("pick-artifact")
    pick.add_argument("--artifacts-json", type=Path, required=True)
    pick.add_argument("--run-json", type=Path, required=True)
    pick.set_defaults(func=_cmd_pick_artifact)
    index = sub.add_parser("build-index")
    index.add_argument("--board-dir", type=Path, required=True)
    index.set_defaults(func=_cmd_build_index)
    row = sub.add_parser("release-row")
    row.add_argument("--board-dir", type=Path, required=True)
    row.add_argument("--sha", default="")
    row.add_argument("--version-ref", required=True)
    row.set_defaults(func=_cmd_release_row)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
