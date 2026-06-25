#!/usr/bin/env python3
"""Resolve the app release coordinate used by staging and production workflows."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_RELEASE_VERSION_REF_RE = re.compile(r"\Av[0-9]+\.[0-9]+\.[0-9]+\Z")


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _out(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            print(f"{key}={value}", file=fh)


def resolve_infra2_release_tag(repo_dir: str = "repo") -> str:
    """Resolve the pinned infra2 submodule to its release TAG (the deploy_v2 iac_ref).

    deploy_v2 staging/prod reject a raw sha: the iac_ref must be a `vX.Y.Z` release
    tag — the immutable, reviewed coordinate that passed infra2's release ritual.
    A git submodule pins by sha, so the app MUST pin its submodule at a tagged infra2
    commit; this resolves that sha back to its exact tag and fails closed otherwise,
    turning "pinned at an unreleased infra2 commit" into a clear error instead of a
    deploy-time `got a 'sha' ref` rejection.
    """
    if not Path(repo_dir).exists():
        raise RuntimeError(f"{repo_dir} submodule is required to resolve iac_ref")
    try:
        iac_sha = _out("git", "-C", repo_dir, "rev-parse", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{repo_dir} is not a readable git repository (cannot resolve iac_ref)"
        ) from exc
    # Tags are not always present after a submodule checkout; fetch them best-effort
    # (silenced — a repo with no `origin` remote, e.g. in tests, is fine here).
    subprocess.run(
        ["git", "-C", repo_dir, "fetch", "--tags", "--quiet", "origin"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        iac_ref = _out(
            "git", "-C", repo_dir, "describe", "--tags", "--exact-match", "HEAD"
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            f"infra2 submodule is pinned at {iac_sha[:12]}, which is NOT a release "
            "tag — deploy_v2 staging/prod require a vX.Y.Z iac_ref. Pin the submodule "
            f"at an infra2 release tag (git -C {repo_dir} checkout vX.Y.Z)."
        ) from None
    if not _RELEASE_VERSION_REF_RE.fullmatch(iac_ref):
        raise RuntimeError(
            f"infra2 submodule tag {iac_ref!r} (at {iac_sha[:12]}) is not a vX.Y.Z "
            "release tag; deploy_v2 requires a release-tag iac_ref."
        )
    return iac_ref


def resolve(version_ref: str) -> dict[str, str]:
    if not _RELEASE_VERSION_REF_RE.fullmatch(version_ref):
        raise ValueError(
            f"version_ref must be a release tag like vX.Y.Z, got {version_ref!r}"
        )

    _run(
        "git",
        "fetch",
        "--no-tags",
        "origin",
        f"refs/tags/{version_ref}:refs/tags/{version_ref}",
    )
    _run("git", "checkout", "--detach", version_ref)
    _run("git", "submodule", "update", "--init", "--recursive")

    full_sha = _out("git", "rev-parse", "HEAD")
    iac_ref = resolve_infra2_release_tag("repo")
    return {
        "version_ref": version_ref,
        "full_sha": full_sha,
        "short_sha": full_sha[:7],
        "iac_ref": iac_ref,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="resolve a vX.Y.Z release tag and pinned infra2 submodule SHA"
    )
    parser.add_argument("--version-ref", required=True)
    args = parser.parse_args(argv)

    try:
        values = resolve(args.version_ref)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"resolve_release_coordinate failed: {exc}", file=sys.stderr)
        return 1

    write_github_output(values)
    print(
        "Resolved release coordinate: "
        f"version_ref={values['version_ref']} "
        f"full_sha={values['full_sha']} "
        f"short_sha={values['short_sha']} "
        f"iac_ref={values['iac_ref']}"
    )
    return 0
