#!/usr/bin/env python3
"""Prune stale GHCR SHA image versions while preserving live deploys."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA_TAG_RE = re.compile(r"^[0-9a-f]{7,40}$")
RELEASE_TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")

GhRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class RetentionDecision:
    version_id: str
    tags: tuple[str, ...]
    action: str
    reason: str


def _default_gh(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _flatten_versions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list) and all(isinstance(page, list) for page in raw):
        return [version for page in raw for version in page if isinstance(version, dict)]
    if isinstance(raw, list):
        return [version for version in raw if isinstance(version, dict)]
    return []


def load_versions(raw_text: str) -> list[dict[str, Any]]:
    if not raw_text.strip():
        return []
    return _flatten_versions(json.loads(raw_text))


def _parse_created_at(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _container_tags(version: dict[str, Any]) -> tuple[str, ...]:
    metadata = version.get("metadata") or {}
    container = metadata.get("container") or {}
    tags = container.get("tags") or []
    return tuple(str(tag) for tag in tags if str(tag).strip())


def _normalize_live_shas(values: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        candidate = value.strip().lower()
        if not SHA_TAG_RE.match(candidate):
            continue
        normalized.add(candidate)
        if len(candidate) >= 7:
            normalized.add(candidate[:7])
    return normalized


def _is_live_sha_tag(tag: str, live_shas: set[str]) -> bool:
    tag = tag.lower()
    if tag in live_shas:
        return True
    return len(tag) >= 7 and tag[:7] in live_shas


def select_retention_decisions(
    versions: Iterable[dict[str, Any]],
    *,
    retention_days: int,
    live_shas: Iterable[str],
    now: dt.datetime | None = None,
) -> list[RetentionDecision]:
    """Classify GHCR package versions for stale SHA tag pruning."""

    reference_time = now or dt.datetime.now(dt.UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=dt.UTC)
    cutoff = reference_time.astimezone(dt.UTC) - dt.timedelta(days=retention_days)
    normalized_live_shas = _normalize_live_shas(live_shas)

    decisions: list[RetentionDecision] = []
    for version in versions:
        version_id = str(version.get("id") or "").strip()
        tags = _container_tags(version)
        sha_tags = tuple(tag for tag in tags if SHA_TAG_RE.match(tag.lower()))

        if not version_id:
            continue
        if not sha_tags:
            decisions.append(
                RetentionDecision(version_id, tags, "keep", "no-sha-tag")
            )
            continue
        if any(RELEASE_TAG_RE.match(tag) for tag in tags):
            decisions.append(
                RetentionDecision(version_id, tags, "keep", "release-tag")
            )
            continue
        if any(_is_live_sha_tag(tag, normalized_live_shas) for tag in sha_tags):
            decisions.append(
                RetentionDecision(version_id, tags, "keep", "live-deploy-sha")
            )
            continue

        created = _parse_created_at(str(version.get("created_at") or ""))
        if created is None:
            decisions.append(
                RetentionDecision(version_id, tags, "skip", "invalid-created-at")
            )
            continue
        if created >= cutoff:
            decisions.append(
                RetentionDecision(version_id, tags, "keep", "retention-window")
            )
            continue

        decisions.append(RetentionDecision(version_id, tags, "delete", "stale-sha"))
    return decisions


def _load_live_shas(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _list_versions(
    *,
    gh: GhRunner,
    package_scope_path: str,
    image_name: str,
) -> list[dict[str, Any]]:
    result = gh(
        [
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"{package_scope_path}/packages/container/{image_name}/versions",
            "--paginate",
            "--slurp",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{image_name}: failed to list GHCR package versions: {result.stderr.strip()}"
        )
    return load_versions(result.stdout)


def _delete_version(
    *,
    gh: GhRunner,
    package_scope_path: str,
    image_name: str,
    version_id: str,
) -> None:
    result = gh(
        [
            "api",
            "--method",
            "DELETE",
            "-H",
            "Accept: application/vnd.github+json",
            f"{package_scope_path}/packages/container/{image_name}/versions/{version_id}",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{image_name}: failed to delete GHCR package version {version_id}: "
            f"{result.stderr.strip()}"
        )


def prune_ghcr_sha_images(
    *,
    package_scope_path: str,
    image_names: Sequence[str],
    retention_days: int,
    live_shas: Sequence[str],
    dry_run: bool,
    gh: GhRunner = _default_gh,
) -> int:
    if retention_days < 1:
        raise ValueError("retention-days must be positive")
    if not _normalize_live_shas(live_shas):
        raise ValueError("at least one live deploy SHA exemption is required")

    selected_total = 0
    deleted_total = 0
    for image_name in image_names:
        versions = _list_versions(
            gh=gh,
            package_scope_path=package_scope_path,
            image_name=image_name,
        )
        decisions = select_retention_decisions(
            versions,
            retention_days=retention_days,
            live_shas=live_shas,
        )
        for decision in decisions:
            tag_list = ",".join(decision.tags)
            if decision.action == "delete":
                selected_total += 1
                if dry_run:
                    print(
                        f"{image_name}: dry-run delete version={decision.version_id} "
                        f"reason={decision.reason} tags={tag_list}"
                    )
                else:
                    _delete_version(
                        gh=gh,
                        package_scope_path=package_scope_path,
                        image_name=image_name,
                        version_id=decision.version_id,
                    )
                    deleted_total += 1
                    print(
                        f"{image_name}: deleted version={decision.version_id} "
                        f"reason={decision.reason} tags={tag_list}"
                    )
            elif decision.action in {"keep", "skip"}:
                print(
                    f"{image_name}: {decision.action} version={decision.version_id} "
                    f"reason={decision.reason} tags={tag_list}"
                )

    print(f"stale_sha_versions_selected={selected_total}")
    print(f"stale_sha_versions_deleted={deleted_total}")
    print(f"dry_run={str(dry_run).lower()}")
    return selected_total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-scope-path", required=True)
    parser.add_argument("--image-name", action="append", required=True)
    parser.add_argument("--retention-days", type=int, default=28)
    parser.add_argument("--live-shas-file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        live_shas = _load_live_shas(args.live_shas_file)
        prune_ghcr_sha_images(
            package_scope_path=args.package_scope_path,
            image_names=args.image_name,
            retention_days=args.retention_days,
            live_shas=live_shas,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ghcr_retention failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
