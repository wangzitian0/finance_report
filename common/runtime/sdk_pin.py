"""Read the SDK bootstrap artifact from the backend lock without importing the SDK."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def read_sdk_pin(root: Path) -> tuple[str, str, str]:
    """Return validated URL, SHA256 and filename; disagreement blocks acquisition."""
    backend = root / "apps/backend"
    with (backend / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    with (backend / "uv.lock").open("rb") as stream:
        lock = tomllib.load(stream)
    declared = [
        dep.partition(" @ ")[2]
        for dep in project["project"]["dependencies"]
        if dep.partition(" @ ")[0].split("[", 1)[0] == "infra2-sdk"
    ]
    packages = [item for item in lock["package"] if item["name"] == "infra2-sdk"]
    if len(declared) != 1 or len(packages) != 1:
        raise ValueError(
            "infra2-sdk must have exactly one declaration and locked package"
        )
    package = packages[0]
    version = package.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", version
    ):
        raise ValueError("infra2-sdk lock must name an exact release version")
    filename = f"infra2_sdk-{version}-py3-none-any.whl"
    url = f"https://github.com/wangzitian0/infra2-sdk/releases/download/v{version}/{filename}"
    wheels = package.get("wheels", [])
    if declared != [url] or package.get("source") != {"url": url} or len(wheels) != 1:
        raise ValueError("infra2-sdk declaration and locked release wheel disagree")
    wheel = wheels[0]
    digest = wheel.get("hash", "")
    if wheel.get("url") != url or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("infra2-sdk release wheel requires a matching URL and SHA256")
    return url, digest.removeprefix("sha256:"), filename
