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


def resolve(version_ref: str) -> dict[str, str]:
    version_ref = version_ref.strip()
    if not _RELEASE_VERSION_REF_RE.fullmatch(version_ref):
        raise ValueError(
            f"version_ref must be a release tag like vX.Y.Z, got {version_ref!r}"
        )

    _run("git", "fetch", "--force", "--tags", "origin", "refs/tags/*:refs/tags/*")
    _run("git", "checkout", "--detach", version_ref)
    _run("git", "submodule", "update", "--init", "--recursive")

    full_sha = _out("git", "rev-parse", "HEAD")
    repo_dir = Path("repo")
    if not repo_dir.exists():
        raise RuntimeError("repo submodule is required to resolve iac_ref")
    iac_ref = _out("git", "-C", "repo", "rev-parse", "HEAD")
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
