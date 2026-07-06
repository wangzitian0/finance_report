"""Gate: the L4 `backend` super-package boundary — no silent structure loss (#app-boundary).

The un-migrated remainder of ``apps/backend/src`` (``services/`` / ``routers/`` /
``prompts/``) is the L4 ``backend`` app-layer super-package. Until each domain is
carved out, this gate makes the coupling between that remainder and the already-
carved packages **visible and monotonic**:

- **inbound** — a remainder file importing an *unpublished internal* of a carved
  package (``from src.extraction.extension.X import Y`` where ``Y`` ∉
  ``extraction.__all__``) — the encapsulation leak that the core
  ``check_package_contract`` deep-import gate cannot see because the remainder is
  not (yet) a discovered package;
- **outbound** — a carved package importing the app remainder
  (``from src.services.X import Y``) — a domain/infra (L1/L3) → app (L4) **upward
  layer** edge, the chain that stops a carved package from being liftable.

Both directions are frozen in a baseline that may only shrink (``--update``
regenerates). A brand-new edge in either direction fails the gate, so a
completed package can never again silently lose its boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.meta.extension.app_boundary import (
    APP_REMAINDER_SUBDIRS,
    cross_boundary_edges,
    discover_and_compute_edges,
    load_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "docs/ssot/app-boundary-baseline.json"


def _make_pkg(backend_src: Path, name: str, all_symbols: list[str], internal_body: str = "") -> None:
    pkg = backend_src / name
    (pkg / "extension").mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f"__all__ = {all_symbols!r}\n", encoding="utf-8")
    (pkg / "extension" / "internal.py").write_text(internal_body or "SECRET = 1\n", encoding="utf-8")


def test_inbound_leak_detected(tmp_path: Path) -> None:
    """A remainder file reaching an unpublished internal of a carved package is an inbound edge."""
    src = tmp_path / "apps/backend/src"
    (src / "services").mkdir(parents=True)
    _make_pkg(src, "extraction", ["PublicThing"])
    (src / "services" / "leaky.py").write_text(
        "from src.extraction.extension.internal import SECRET\n", encoding="utf-8"
    )
    edges = cross_boundary_edges(
        backend_src=src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=tmp_path,
    )
    assert any(e.startswith("in::") and "SECRET" in e for e in edges)


def test_inbound_published_symbol_is_allowed(tmp_path: Path) -> None:
    """Importing a *published* symbol of a carved package is not an edge."""
    src = tmp_path / "apps/backend/src"
    (src / "services").mkdir(parents=True)
    _make_pkg(src, "extraction", ["PublicThing"])
    (src / "services" / "ok.py").write_text("from src.extraction import PublicThing\n", encoding="utf-8")
    edges = cross_boundary_edges(
        backend_src=src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=tmp_path,
    )
    assert edges == []


def test_outbound_upward_layer_detected(tmp_path: Path) -> None:
    """A carved package importing the app remainder is an outbound (upward-layer) edge."""
    src = tmp_path / "apps/backend/src"
    (src / "services").mkdir(parents=True)
    _make_pkg(src, "extraction", ["PublicThing"])
    (src / "extraction" / "extension" / "reaches_up.py").write_text(
        "from src.services.storage import redact\n", encoding="utf-8"
    )
    edges = cross_boundary_edges(
        backend_src=src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=tmp_path,
    )
    assert any(e.startswith("out::") and "src.services.storage" in e for e in edges)


def test_carved_to_shared_infra_is_not_an_edge(tmp_path: Path) -> None:
    """Importing shared infra (src.database) is out of scope — only app-remainder subdirs count."""
    src = tmp_path / "apps/backend/src"
    (src / "database").mkdir(parents=True)  # NOT in APP_REMAINDER_SUBDIRS
    _make_pkg(src, "ledger", ["Account"])
    (src / "ledger" / "extension" / "repo.py").write_text("from src.database import get_session\n", encoding="utf-8")
    edges = cross_boundary_edges(
        backend_src=src,
        carved={"ledger": "ledger"},
        published={"ledger": {"Account"}},
        repo_root=tmp_path,
    )
    assert edges == []


def test_app_remainder_subdirs_are_the_app_domain_logic() -> None:
    assert APP_REMAINDER_SUBDIRS == frozenset({"services", "routers", "prompts"})


def test_real_repo_edges_are_all_baselined() -> None:
    """Every current cross-boundary edge in the real repo is in the frozen baseline
    (current ⊆ baseline). A new leak — inbound or outbound — fails here."""
    current = set(discover_and_compute_edges(REPO_ROOT))
    baseline = load_baseline(BASELINE)
    new = current - baseline
    assert not new, "NEW cross-boundary edge(s) not in baseline (add via --update only to SHRINK):\n" + "\n".join(
        sorted(new)
    )


def test_baseline_has_no_stale_entries() -> None:
    """The baseline only-shrinks: an entry that no longer exists should be pruned
    (keeps the burndown honest). Warn-level today via a soft assert on the count."""
    current = set(discover_and_compute_edges(REPO_ROOT))
    baseline = load_baseline(BASELINE)
    stale = baseline - current
    assert not stale, f"baseline has {len(stale)} stale entrie(s) — run --update to prune:\n" + "\n".join(sorted(stale))
