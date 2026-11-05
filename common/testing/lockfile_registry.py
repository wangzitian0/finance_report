"""Verify that every tracked package-lock.json resolves packages from the official npm registry (#2668)."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from common.meta.base.gate_cli import run_gate

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_REGISTRY_PREFIX = "https://registry.npmjs.org/"


@dataclass(frozen=True, order=True)
class LockfileRegistryFinding:
    """One non-official registry URL found in a package-lock.json file."""

    lockfile: str
    package_path: str
    resolved_url: str

    def format(self) -> str:
        label = self.package_path or "<root>"
        return (
            f"{self.lockfile}: package {label!r} resolves to non-official registry URL "
            f"{self.resolved_url!r} (expected prefix {ALLOWED_REGISTRY_PREFIX!r})"
        )


def discover_lockfiles(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Return tracked package-lock.json files under repo_root, falling back to rglob when untracked."""
    proc = subprocess.run(
        ["git", "ls-files", "*package-lock.json", "**/package-lock.json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        tracked = sorted(
            {
                repo_root / line.strip()
                for line in proc.stdout.splitlines()
                if line.strip() and (repo_root / line.strip()).is_file()
            }
        )
        if tracked:
            return tracked
    return sorted(
        path
        for path in repo_root.rglob("package-lock.json")
        if "node_modules" not in path.parts and ".git" not in path.parts
    )


def scan_lockfile(
    lockfile_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    allowed_prefix: str = ALLOWED_REGISTRY_PREFIX,
) -> list[LockfileRegistryFinding]:
    """Inspect a single package-lock.json and return any non-official registry findings."""
    try:
        rel_path = lockfile_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel_path = lockfile_path.as_posix()

    try:
        payload = json.loads(lockfile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            LockfileRegistryFinding(
                lockfile=rel_path,
                package_path="<invalid-json>",
                resolved_url=f"unparseable lockfile: {exc}",
            )
        ]

    if not isinstance(payload, dict):
        return [
            LockfileRegistryFinding(
                lockfile=rel_path,
                package_path="<root>",
                resolved_url="lockfile root is not a JSON object",
            )
        ]

    packages = payload.get("packages")
    if not isinstance(packages, dict) or not packages:
        return [
            LockfileRegistryFinding(
                lockfile=rel_path,
                package_path="<packages>",
                resolved_url="lockfile 'packages' map is missing or empty",
            )
        ]

    findings: list[LockfileRegistryFinding] = []
    resolved_count = 0
    for pkg_path, meta in sorted(packages.items()):
        if not isinstance(meta, dict):
            continue
        resolved = meta.get("resolved")
        if resolved is None:
            continue
        resolved_count += 1
        if not isinstance(resolved, str) or not resolved.startswith(allowed_prefix):
            findings.append(
                LockfileRegistryFinding(
                    lockfile=rel_path,
                    package_path=str(pkg_path),
                    resolved_url=str(resolved),
                )
            )
    if resolved_count == 0:
        findings.append(
            LockfileRegistryFinding(
                lockfile=rel_path,
                package_path="<packages>",
                resolved_url="lockfile contains zero resolved package URLs",
            )
        )
    return findings


def violations(
    repo_root: Path = REPO_ROOT,
    *,
    lockfiles: Sequence[Path] | None = None,
    allowed_prefix: str = ALLOWED_REGISTRY_PREFIX,
) -> list[str]:
    """Return formatted violation strings across all discovered or specified lockfiles."""
    targets = list(lockfiles) if lockfiles is not None else discover_lockfiles(repo_root)
    if not targets:
        return [f"no package-lock.json files found under {repo_root}"]
    all_findings: list[LockfileRegistryFinding] = []
    for lockfile in targets:
        all_findings.extend(
            scan_lockfile(lockfile, repo_root=repo_root, allowed_prefix=allowed_prefix)
        )
    return [finding.format() for finding in all_findings]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--lockfile",
        action="append",
        type=Path,
        dest="lockfiles",
        default=None,
        help="Explicit package-lock.json path(s) to check (defaults to tracked package-lock.json files).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    repo_root = args.repo_root.resolve()
    explicit_lockfiles = (
        [
            path if path.is_absolute() else (repo_root / path)
            for path in args.lockfiles
        ]
        if args.lockfiles
        else None
    )
    return run_gate(
        "LOCKFILE-REGISTRY",
        lambda root: violations(root, lockfiles=explicit_lockfiles),
        ["--repo-root", str(repo_root)],
        annotation_title="Lockfile Registry Check",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
