#!/usr/bin/env python3
"""Resolve the app release coordinate used by staging and production workflows."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from common.runtime.github_api import write_github_output

_RELEASE_VERSION_REF_RE = re.compile(r"\Av[0-9]+\.[0-9]+\.[0-9]+\Z")


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _out(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def build_release_coordinate(version_ref: str, full_sha: str) -> dict[str, str]:
    """Pure assembly of the release-coordinate dict `resolve()` emits.

    Split out so the coordinate SHAPE (short_sha is a 7-char prefix of
    full_sha, the field set) is unit-testable without the git mutations
    `resolve()` performs (fetch/checkout) — see
    tests/tooling/test_release_coordinate.py.
    """
    return {
        "version_ref": version_ref,
        "full_sha": full_sha,
        "short_sha": full_sha[:7],
    }


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

    full_sha = _out("git", "rev-parse", "HEAD")
    return build_release_coordinate(version_ref, full_sha)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="resolve a Finance Report vX.Y.Z release tag"
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
        f"short_sha={values['short_sha']}"
    )
    return 0
