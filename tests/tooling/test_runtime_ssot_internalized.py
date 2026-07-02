"""Guard: the runtime migration is complete — no runtime-exclusive SSOT/EPIC content lingers.

The `runtime` package owns the app↔external-world dependency boundary, including the
environment smoke-test / Three-Gates verification that once lived in the central
`docs/ssot/env_smoke_test.md`. Per the package-migration standard
(``common/meta/migration-standard.md``, step 3 "SSOT internalized" — *a lingering
original means NOT migrated*), that content is internalized into the package readme
and the central doc is retired. These assertions fail if the doc is resurrected or
its ownership drifts back out of the package.
"""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_env_smoke_test_doc_is_retired() -> None:
    """The central env-smoke-test SSOT doc no longer exists — it lives in the package."""
    assert not (ROOT / "docs/ssot/env_smoke_test.md").exists()


def test_runtime_readme_owns_the_three_gates() -> None:
    """The internalized Three-Gates verification now lives in the runtime package readme."""
    readme = read("common/runtime/readme.md")
    assert "Environment verification (the Three Gates)" in readme
    # The gate ladder + boot-vs-smoke distinction (was env_smoke_test.md's core).
    for token in (
        "1 Static",
        "2 Startup",
        "3 Health",
        "tools/smoke_test.sh",
        "src.boot",
    ):
        assert token in readme


def test_manifest_env_smoke_test_owner_is_the_package() -> None:
    """MANIFEST repoints the env_smoke_test concept to the package readme (owner), not a central doc."""
    manifest = yaml.safe_load(read("docs/ssot/MANIFEST.yaml"))
    owner = manifest["concepts"]["env_smoke_test"]["owner"]
    assert owner.startswith("common/runtime/readme.md")
    # No cross_ref (or owner) may resurrect the retired central doc.
    assert "docs/ssot/env_smoke_test.md" not in yaml.dump(manifest)


def test_no_ssot_or_epic_doc_references_the_retired_doc() -> None:
    """No living SSOT/EPIC doc links to the retired env_smoke_test.md path."""
    stale: list[str] = []
    for base in ("docs/ssot", "docs/project"):
        for path in (ROOT / base).rglob("*.md"):
            if "docs/ssot/env_smoke_test.md" in path.read_text(encoding="utf-8"):
                stale.append(str(path.relative_to(ROOT)))
    assert not stale, f"stale references to the retired doc: {stale}"
