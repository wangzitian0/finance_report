#!/usr/bin/env python3
"""Verify retained backend/frontend release image digests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable

InspectImage = Callable[[str], tuple[int, str]]


def _default_inspect_image(image: str) -> tuple[int, str]:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode, result.stdout


def _write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            print(f"{key}={value}", file=fh)


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
) -> dict[str, str]:
    digests: dict[str, str] = {}
    for service in ("backend", "frontend"):
        image = f"{registry}/{image_prefix}-{service}:{version_ref}"
        rc, output = inspect_image(image)
        digest = _extract_digest(output) if rc == 0 else ""
        if not digest:
            raise RuntimeError(f"Release image not found: {image}")
        print(f"Found {service} release image digest: {digest}")
        digests[f"{service}_digest"] = digest
    return digests


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main(argv: list[str] | None = None) -> int:
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
