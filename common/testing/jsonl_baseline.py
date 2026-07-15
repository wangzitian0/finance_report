"""Parameterized JSONL storage and monotonic merge for persisted ratchets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASELINE_VERSION = 1


def _normalize_record(
    identifier: str,
    record: dict[str, Any],
    *,
    identifier_key: str,
    default_metric: str,
) -> dict[str, Any]:
    return {
        identifier_key: identifier,
        "score": round(float(record.get("score", 0.0)), 6),
        "metric": record.get("metric", default_metric),
        "provenance": record.get("provenance", ""),
    }


def _ordered_line(record: dict[str, Any], *, identifier_key: str) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (identifier_key, "score", "metric", "provenance")
        if key in record
    }


def records_to_lines(
    records: dict[str, dict[str, Any]],
    *,
    identifier_key: str,
    default_metric: str = "",
) -> list[str]:
    """Render a keyed record mapping as sorted, deterministic JSONL lines."""

    return [
        json.dumps(
            _ordered_line(
                _normalize_record(
                    identifier,
                    records[identifier],
                    identifier_key=identifier_key,
                    default_metric=default_metric,
                ),
                identifier_key=identifier_key,
            ),
            sort_keys=False,
            ensure_ascii=False,
        )
        for identifier in sorted(records)
    ]


def render_jsonl(
    payload: dict[str, Any],
    *,
    identifier_key: str,
    collection_key: str,
    default_metric: str = "",
) -> str:
    """Render a payload's keyed collection as canonical JSONL."""

    records = payload.get(collection_key, {})
    if not isinstance(records, dict):
        records = {}
    body = "\n".join(
        records_to_lines(
            records,
            identifier_key=identifier_key,
            default_metric=default_metric,
        )
    )
    return f"{body}\n" if body else ""


def load_jsonl(
    path: Path,
    *,
    identifier_key: str,
    collection_key: str,
    default_metric: str = "",
) -> dict[str, Any]:
    """Load a JSONL baseline into its in-memory versioned mapping shape."""

    records: dict[str, dict[str, Any]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSONL line: {exc}") from exc
        if not isinstance(record, dict) or identifier_key not in record:
            raise ValueError(
                f"{path}:{lineno}: each line must be a JSON object with an "
                f"{identifier_key!r}"
            )
        identifier = str(record[identifier_key])
        if identifier in records:
            raise ValueError(
                f"{path}:{lineno}: duplicate {identifier_key} {identifier!r} "
                "-- resolve the same-record ratchet conflict (keep the higher floor)"
            )
        records[identifier] = {
            "score": round(float(record.get("score", 0.0)), 6),
            "metric": record.get("metric", default_metric),
            "provenance": record.get("provenance", ""),
        }
    return {"version": BASELINE_VERSION, collection_key: records}


def write_jsonl(
    path: Path,
    payload: dict[str, Any],
    *,
    identifier_key: str,
    collection_key: str,
    default_metric: str = "",
) -> None:
    """Write a payload as canonical JSONL, creating its parent as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_jsonl(
            payload,
            identifier_key=identifier_key,
            collection_key=collection_key,
            default_metric=default_metric,
        ),
        encoding="utf-8",
    )


def normalize_file(
    path: Path,
    *,
    identifier_key: str,
    collection_key: str,
    default_metric: str = "",
) -> dict[str, Any]:
    """Re-sort and normalize one JSONL baseline in place."""

    payload = load_jsonl(
        path,
        identifier_key=identifier_key,
        collection_key=collection_key,
        default_metric=default_metric,
    )
    write_jsonl(
        path,
        payload,
        identifier_key=identifier_key,
        collection_key=collection_key,
        default_metric=default_metric,
    )
    return payload


def ratcheted_raise_only_merge(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    collection_key: str,
    default_metric: str = "",
) -> dict[str, Any]:
    """Merge per-record floors, preserving the higher score for every identifier."""

    baseline_records = baseline.get(collection_key, {})
    current_records = current.get(collection_key, {})
    merged = dict(baseline_records) if isinstance(baseline_records, dict) else {}
    if not isinstance(current_records, dict):
        current_records = {}

    for identifier, current_record in current_records.items():
        if not isinstance(current_record, dict):
            continue
        previous = merged.get(identifier)
        current_score = float(current_record.get("score", 0.0))
        if not isinstance(previous, dict) or current_score >= float(
            previous.get("score", 0.0)
        ):
            merged[identifier] = {
                "score": round(current_score, 6),
                "metric": current_record.get("metric", default_metric),
                "provenance": current_record.get("provenance", ""),
            }
    return {"version": BASELINE_VERSION, collection_key: dict(sorted(merged.items()))}
