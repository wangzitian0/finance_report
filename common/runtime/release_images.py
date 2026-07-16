#!/usr/bin/env python3
"""Verify retained backend/frontend release image digests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence

from common.runtime.github_api import write_github_output as _write_github_output

InspectImage = Callable[[str], tuple[int, str]]
Sleep = Callable[[float], None]


def _default_inspect_image(image: str) -> tuple[int, str]:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode, result.stdout


def _extract_digest(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Digest:"):
            return line.split(":", 1)[1].strip()
    return ""


def verify_release_images(
    *,
    registry: str,
    image_prefix: str,
    version_ref: str,
    inspect_image: InspectImage = _default_inspect_image,
    max_attempts: int = 4,
    retry_delay_seconds: float = 3.0,
    sleep: Sleep = time.sleep,
) -> dict[str, str]:
    """Inspect the backend/frontend images, retrying on a not-yet-visible digest.

    A registry inspect immediately after a push can race the registry's own
    propagation (seconds, not minutes) — most callers (release.yml's dry-run/
    deploy against an already-published release tag) never hit this in
    practice, but the freshest caller (CI's verify-sha-image-published, which
    inspects the :<sha> tag right after container-images pushes it on every
    main commit) can. Retrying a bounded number of times before failing
    closed avoids that transient flake without weakening the guarantee: an
    image that truly never appears still fails after max_attempts.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if retry_delay_seconds < 0:
        raise ValueError(f"retry_delay_seconds must be >= 0, got {retry_delay_seconds}")

    digests: dict[str, str] = {}
    for service in ("backend", "frontend"):
        image = f"{registry}/{image_prefix}-{service}:{version_ref}"
        digest = ""
        rc = 0
        for attempt in range(1, max_attempts + 1):
            rc, output = inspect_image(image)
            digest = _extract_digest(output) if rc == 0 else ""
            if digest:
                break
            if attempt < max_attempts:
                # rc included, and no root cause asserted: a non-zero rc can be
                # registry propagation lag, but can just as well be an auth or
                # tooling error -- printing rc keeps that diagnosable instead
                # of always blaming "not yet visible".
                print(
                    f"Inspect did not return a digest (rc={rc}, attempt "
                    f"{attempt}/{max_attempts}): {image} — retrying in "
                    f"{retry_delay_seconds}s"
                )
                sleep(retry_delay_seconds)
        if not digest:
            raise RuntimeError(
                f"Release image not found after {max_attempts} attempts "
                f"(last rc={rc}): {image}"
            )
        print(f"Found {service} release image digest: {digest}")
        digests[f"{service}_digest"] = digest
    return digests


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=os.getenv("REGISTRY", ""))
    parser.add_argument("--image-prefix", default=os.getenv("IMAGE_PREFIX", ""))
    parser.add_argument("--version-ref", default=os.getenv("VERSION_REF", ""))
    args = parser.parse_args(argv)

    try:
        digests = verify_release_images(
            registry=_required(args.registry, "registry"),
            image_prefix=_required(args.image_prefix, "image-prefix"),
            version_ref=_required(args.version_ref, "version-ref"),
        )
    except (ValueError, RuntimeError) as exc:
        print(f"verify_release_images failed: {exc}", file=sys.stderr)
        return 1

    _write_github_output(digests)
    return 0
