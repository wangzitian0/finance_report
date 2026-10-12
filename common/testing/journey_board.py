#!/usr/bin/env python3
"""Core-journey board: one record per staging lane run (#2370).

Heavy board, light gates. This module turns the artifact of one staging
AI/OCR gate run into one record. It also regenerates the board index and the
board HTML fragment from all records. It blocks nothing.

The module uses only the standard library. The publisher job runs it with the
runner's ``python3`` and installs no project dependencies.

Records hold test identities, outcomes, statuses and run links only. They
never hold amounts, fixture values or failure text (vision Axiom C).
"""

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

GATE_XML = "staging-ai-ocr-gate.xml"
RETRY_XML = "staging-ai-ocr-retry.xml"
CONTEXT_FILE = "staging-ai-ocr-context.txt"
MANIFEST_FILE = "staging-ai-ocr-manifest.json"
# The reusable gate job shows as "<caller job> / Staging AI/OCR Gate" in a
# run: "Staging AI/OCR Gate / ..." in Deploy, "AI/OCR Audit Replay / ..." in
# the replay. The skipped manual Deploy job has no " / " and never matches.
GATE_JOB_NAME = "Staging AI/OCR Gate"
GATE_JOB_SUFFIX = f" / {GATE_JOB_NAME}"
# A skipped reusable call shows only as "Staging AI/OCR Gate" (no suffix), the
# same as the skipped manual job. "Deploy Staging" marks a staging deploy run.
DEPLOY_STAGING_JOB = "Deploy Staging"
# A run's "name" is its run-name (for example "Deploy Staging v0.1.75"), not
# the workflow name, so the workflow file path identifies the workflow.
DEPLOY_WORKFLOW = ".github/workflows/deploy.yml"
REPLAY_WORKFLOW = ".github/workflows/audit-replay.yml"
BOARD_WORKFLOWS = (DEPLOY_WORKFLOW, REPLAY_WORKFLOW)
LANES = ("canary", "core_journey", "audit_replay", "all")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

INDEX_CAP = 200
MATRIX_COLUMNS = 10
# An audit replay runs weekly. A record older than this is stale.
AUDIT_REPLAY_STALE_DAYS = 8

# Checkpoint statuses, worst first. A cell shows the worst status of the
# proofs that ran. "passed" is better than "not-run", so one proof that ran
# and passed is not hidden by a proof that did not run.
CHECKPOINT_STATUS_ORDER = (
    "failed",
    "unproven",
    "blocked",
    "skipped",
    "passed",
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


def load_checkpoint_map(path: Path = CHECKPOINT_MAP_PATH) -> CheckpointMap:
    """Load the checkpoint map and reject a proof that names an unknown checkpoint."""
    data = json.loads(path.read_text(encoding="utf-8"))
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
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def parse_junit(path: Path) -> list[Case]:
    """Read one JUnit XML file into cases with their reached checkpoints."""
    root = ET.parse(path).getroot()
    cases: list[Case] = []
    for element in root.iter("testcase"):
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
                test_id=f"{classname}::{name}" if classname else name,
                outcome=_case_outcome(element),
                seconds=round(float(element.get("time") or 0.0), 2),
                reached=reached,
            )
        )
    return cases


def merge_retry(first: list[Case], retry: list[Case]) -> list[Case]:
    """Apply the gate's single transient retry to the first-pass cases.

    The retry re-runs whole files. A case that failed and then passed on retry
    becomes ``passed-on-retry``. A retried case that failed keeps the retry
    failure, also when its first pass passed.
    """
    retried = {case.test_id: case for case in retry}
    merged: list[Case] = []
    for case in first:
        again = retried.get(case.test_id)
        if again is None:
            merged.append(case)
        elif again.outcome in FAILED_OUTCOMES:
            merged.append(again)
        elif case.outcome not in FAILED_OUTCOMES:
            merged.append(case)
        elif again.outcome == "passed":
            merged.append(
                Case(
                    case.test_id, "passed-on-retry", again.seconds, list(again.reached)
                )
            )
        else:
            merged.append(again)
    return merged


def proof_checkpoint_statuses(case: Case | None, proof: Proof) -> dict[str, str]:
    """Status of each checkpoint that one proof covers.

    A failed test proved the checkpoints it reached. The first checkpoint it
    did not reach failed. The checkpoints after that one are blocked. A passed
    test that did not reach a mapped checkpoint is ``unproven``: the map and
    the test disagree, and the board shows that as red.
    """
    if case is None:
        return {checkpoint: "not-run" for checkpoint in proof.reaches}
    if case.outcome == "skipped":
        return {checkpoint: "skipped" for checkpoint in proof.reaches}
    if case.outcome in PASSED_OUTCOMES:
        return {
            checkpoint: "passed" if checkpoint in case.reached else "unproven"
            for checkpoint in proof.reaches
        }
    statuses: dict[str, str] = {}
    failure_seen = False
    for checkpoint in proof.reaches:
        if checkpoint in case.reached:
            statuses[checkpoint] = "passed"
        elif not failure_seen:
            statuses[checkpoint] = "failed"
            failure_seen = True
        else:
            statuses[checkpoint] = "blocked"
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
    for checkpoint in checkpoint_map.checkpoints:
        proofs = [
            {"test": proof.test, "status": per_proof[proof.test][checkpoint.id]}
            for proof in checkpoint_map.proofs
            if checkpoint.id in proof.reaches
        ]
        if not proofs:
            rollup[checkpoint.id] = {"status": "not-covered", "gap": checkpoint.gap}
            continue
        rollup[checkpoint.id] = {
            "status": worst([proof["status"] for proof in proofs]),
            "proofs": proofs,
        }
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
    """Build the record for one gate run, or ``None`` when there is nothing to record.

    A Deploy run with no staging deploy and no gate run (a tag-push image
    promotion) has nothing to record. A staging deploy whose gate did not run,
    or a gate run with no artifact, gives a ``not-run`` or ``no-evidence``
    record: the board must show a missing proof, not hide it.
    """
    if run.get("path") not in BOARD_WORKFLOWS:
        raise ValueError(
            f"run {run.get('id')} is not a {' or '.join(BOARD_WORKFLOWS)} run"
        )
    gate_jobs = [job for job in jobs if _is_gate_job(job.get("name", ""))]
    ran = [job for job in gate_jobs if job.get("conclusion") not in (None, "skipped")]
    deploy_jobs = [job for job in jobs if job.get("name") == DEPLOY_STAGING_JOB]
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
            item["test"]: item.get("subtype") or item.get("class")
            for item in json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "cases", []
            )
        }
        for case in cases:
            if case.outcome in FAILED_OUTCOMES:
                case.failure_class = classes.get(case.test_id)
    return _record(
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
    """One file per run attempt, grouped by tested SHA for the release lookup."""
    run = record["run"]
    sha_dir = record["tested_sha"] or "unknown"
    return (
        board_dir
        / "records"
        / sha_dir
        / f"{record['lane']}-{run['id']}-{run['attempt']}.json"
    )


def _preference(record: dict[str, Any]) -> tuple[bool, str]:
    return (record.get("tested_sha") is not None, record.get("recorded_at") or "")


def load_records(board_dir: Path) -> list[dict[str, Any]]:
    """Read every record. One run attempt keeps one record.

    A record with a tested SHA wins over one without; then the later
    ``recorded_at`` wins. The file path never decides.
    """
    by_run: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted((board_dir / "records").rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != SCHEMA_VERSION:
            continue
        key = (record["run"]["id"], record["run"]["attempt"])
        current = by_run.get(key)
        if current is None or _preference(record) > _preference(current):
            by_run[key] = record
    return sorted(
        by_run.values(), key=lambda record: record["run"]["completed_at"], reverse=True
    )


def build_index(
    records: list[dict[str, Any]], checkpoint_map: CheckpointMap, *, generated_at: str
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": generated_at,
        "checkpoints": [
            {"id": checkpoint.id, "title": checkpoint.title, "gap": checkpoint.gap}
            for checkpoint in checkpoint_map.checkpoints
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
    lanes = latest_by_lane(
        [record for record in records if record["tested_sha"] == sha]
    )
    combined: dict[str, dict[str, Any]] = {}
    for lane_record in lanes.values():
        for checkpoint_id, cell in lane_record["checkpoints"].items():
            current = combined.get(checkpoint_id)
            if current is None or CHECKPOINT_STATUS_ORDER.index(
                cell["status"]
            ) < CHECKPOINT_STATUS_ORDER.index(current["status"]):
                combined[checkpoint_id] = {
                    "status": cell["status"],
                    "lane": lane_record["lane"],
                    "url": lane_record["run"]["url"],
                    "gap": cell.get("gap"),
                }
    return combined


def stale_reason(
    record: dict[str, Any], latest: dict[str, dict[str, Any]]
) -> str | None:
    """A core-journey record is stale when it did not test the newest canary SHA."""
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
    if status in ("passed", "passed-on-retry"):
        return "ok"
    if status in ("not-run", "not-covered", "skipped"):
        return "none"
    return "bad"


def _lane_class(record: dict[str, Any]) -> str:
    """Green only with test evidence: a JUnit file, a pass and no failure."""
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


def render_fragment(index: dict[str, Any]) -> str:
    """Render the board as an HTML fragment. The page script adds data age."""
    records = index["records"]
    parts = [
        '<p class="generated">Board generated '
        f'<time data-ts="{escape(index["generated_at"])}">{escape(index["generated_at"])}</time>. '
        "Records hold outcomes only. The board blocks nothing.</p>"
    ]
    if not records:
        parts.append('<p class="bad">No lane run has published a record yet.</p>')
        return "\n".join(parts)

    latest = latest_by_lane(records)
    parts.append("<h2>Latest run per lane</h2>")
    parts.append(
        "<table><thead><tr><th>Lane</th><th>Status</th><th>Tested SHA</th>"
        "<th>Version</th><th>Completed</th><th>Tests</th></tr></thead><tbody>"
    )
    for lane, record in sorted(latest.items()):
        counts = record["counts"]
        stale_days = AUDIT_REPLAY_STALE_DAYS if lane == "audit_replay" else ""
        stale = stale_reason(record, latest)
        status = escape(_lane_label(record))
        parts.append(
            "<tr>"
            f"<td>{escape(lane)}</td>"
            f'<td class="{_lane_class(record)}"><a href="{escape(record["run"]["url"])}">{status}</a></td>'
            f"<td>{_short(record['tested_sha'])}</td>"
            f"<td>{escape(record['expected_version'] or '')}</td>"
            f'<td><time data-ts="{escape(record["run"]["completed_at"])}" data-stale-days="{stale_days}">'
            f"{escape(record['run']['completed_at'])}</time>"
            + (f' <span class="bad">STALE: {escape(stale)}</span>' if stale else "")
            + "</td>"
            f"<td>{counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")

    shas: list[str] = []
    for record in records:
        if record["tested_sha"] and record["tested_sha"] not in shas:
            shas.append(record["tested_sha"])
    shas = shas[:MATRIX_COLUMNS]
    parts.append("<h2>Core journey checkpoints by tested SHA</h2>")
    header = "".join(f"<th>{_short(sha)}</th>" for sha in shas)
    parts.append(f"<table><thead><tr><th>Checkpoint</th>{header}</tr></thead><tbody>")
    combined = {sha: combine_for_sha(records, sha) for sha in shas}
    for checkpoint in index["checkpoints"]:
        cells = []
        for sha in shas:
            cell = combined[sha].get(checkpoint["id"])
            if cell is None:
                cells.append('<td class="none">not-run</td>')
                continue
            label = escape(cell["status"])
            if cell["status"] == "not-covered":
                label += f" {escape(cell.get('gap') or '')}"
                cells.append(f'<td class="none">{label}</td>')
            else:
                cells.append(
                    f'<td class="{_status_class(cell["status"])}">'
                    f'<a href="{escape(cell["url"])}">{label}</a> ({escape(cell["lane"])})</td>'
                )
        parts.append(
            f"<tr><th>{escape(checkpoint['id'])} {escape(checkpoint['title'])}</th>{''.join(cells)}</tr>"
        )
    parts.append("</tbody></table>")

    parts.append("<h2>Tests in the latest run per lane</h2>")
    for lane, record in sorted(latest.items()):
        parts.append(f"<h3>{escape(lane)} · {_short(record['tested_sha'])}</h3>")
        if not record["tests"]:
            parts.append(
                f'<p class="none">No test ran: {escape(record["reason"] or record["status"])}</p>'
            )
            continue
        parts.append("<ul>")
        for test in record["tests"]:
            detail = (
                f" [{escape(test['failure_class'])}]" if test["failure_class"] else ""
            )
            parts.append(
                f'<li class="{_status_class(test["outcome"])}">{escape(test["outcome"])}: '
                f"<code>{escape(test['test'])}</code>{detail}</li>"
            )
        parts.append("</ul>")
    return "\n".join(parts)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def map_for_tested_revision(path: Path | None) -> tuple[CheckpointMap, str | None]:
    """Use the checkpoint map of the tested revision.

    The tests run from the deployed revision, so their marks belong to that
    revision's map. A revision without a map proves no checkpoint: keep the
    current checkpoint list and drop every proof, so nothing shows as proven.
    """
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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"record: {target}")
    return 0


def _cmd_build_index(args: argparse.Namespace) -> int:
    records = load_records(args.board_dir)
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    index = build_index(records, load_checkpoint_map(), generated_at=generated_at)
    (args.board_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.board_dir / "fragment.html").write_text(
        render_fragment(index) + "\n", encoding="utf-8"
    )
    print(f"index: {len(index['records'])} records")
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
    record.add_argument(
        "--repository", required=True, help="owner/name; the run must belong to it"
    )
    record.add_argument(
        "--checkpoint-map",
        type=Path,
        default=None,
        help="checkpoint map of the tested revision; a missing file means the revision has none",
    )
    record.set_defaults(func=_cmd_build_record)
    index = sub.add_parser(
        "build-index", help="regenerate index.json and fragment.html"
    )
    index.add_argument("--board-dir", type=Path, required=True)
    index.set_defaults(func=_cmd_build_index)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
