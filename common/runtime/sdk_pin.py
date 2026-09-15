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
    table = project.get("project")
    if not isinstance(table, dict):
        raise ValueError("pyproject.toml: project must be a table")
    dependencies = table.get("dependencies")
    if not isinstance(dependencies, list) or any(
        not isinstance(dep, str) for dep in dependencies
    ):
        raise ValueError("pyproject.toml: project.dependencies must be a string array")
    locked_packages = lock.get("package")
    if not isinstance(locked_packages, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str)
        for item in locked_packages
    ):
        raise ValueError("uv.lock: package must be an array of named tables")
    declared = [
        dep.partition(" @ ")[2]
        for dep in dependencies
        if dep.partition(" @ ")[0].split("[", 1)[0] == "infra2-sdk"
    ]
    packages = [item for item in locked_packages if item["name"] == "infra2-sdk"]
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
    if not isinstance(wheels, list) or any(
        not isinstance(wheel, dict) for wheel in wheels
    ):
        raise ValueError("uv.lock: infra2-sdk wheels must be an array of tables")
    if declared != [url] or package.get("source") != {"url": url} or len(wheels) != 1:
        raise ValueError("infra2-sdk declaration and locked release wheel disagree")
    wheel = wheels[0]
    digest = wheel.get("hash", "")
    if (
        wheel.get("url") != url
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ):
        raise ValueError("infra2-sdk release wheel requires a matching URL and SHA256")
    return url, digest.removeprefix("sha256:"), filename
