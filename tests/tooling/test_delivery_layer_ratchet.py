"""AC-meta.delivery.1 — the app delivery layer thin-ness ratchet (#1763).

``routers/`` (HTTP delivery adapters) and ``schemas/`` (API DTOs) are the
**sanctioned app delivery layer** — the hexagonal primary adapters of the
application, not domain behavior (#1763 ruling; ``common/meta/
migration-standard.md`` → "The app delivery layer"). The sanction's teeth:
they may hold routing and serialization glue only, so their bulk may only
*shrink* as packages absorb logic. This ratchet approximates "no domain
logic in the delivery layer" with a shrink-only line-count baseline — the
census idiom of ``fk-cascade-baseline.json``, coarsened to lines so router
edits don't churn it.

Census semantics (precise): for each of ``apps/backend/src/routers`` and
``apps/backend/src/schemas``, the census is the **sum over every ``*.py``
file under that directory (recursive, ``__pycache__`` excluded) of
``len(text.splitlines())``**. The baseline
(``common/meta/data/delivery-layer-baseline.json``) maps each directory to its
sanctioned line total.

What CI enforces, per directory, against ``TOLERANCE_LINES = 50``:

- ``census > baseline + 50`` **fails** — meaningful growth. Silent growth is
  impossible; growing the delivery layer requires raising the baseline in
  the same PR, where the diff makes the choice reviewable (the app-boundary
  idiom): legitimate only for genuine delivery glue (a new endpoint's
  routing/DTO surface), never for domain logic.
- ``census < baseline - 50`` **fails** — meaningful shrink (good!) must
  lower the baseline to the new census in the same PR so the ratchet stays
  tight and the burndown is visible.
- within the ±50 band — no action; small refactors and 2-line diffs never
  flake the gate. The band is slack the ratchet tolerates, not headroom
  that accumulates: the baseline is fixed, so repeated small growths still
  hit the ``+50`` ceiling.

``prompts/`` is deliberately NOT in the census: it is domain content, not
delivery, and dissolves into its owning packages (#1763; reconciliation's
prompt already lives in ``src/reconciliation/base/prompts.py``, the advisor
prompt moves with #1671 Wave B).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO / "common/meta/data/delivery-layer-baseline.json"

#: The sanctioned delivery-layer directories, relative to the repo root.
DELIVERY_DIRS = (
    "apps/backend/src/routers",
    "apps/backend/src/schemas",
)

#: Per-directory slack band (lines) — wide enough that renames and small
#: refactors never churn the baseline, narrow enough that a new feature's
#: worth of code cannot land without a reviewable baseline edit.
TOLERANCE_LINES = 50


def _delivery_census() -> dict[str, dict[str, int]]:
    """Per-directory ``{"files": N, "lines": M}`` for the delivery layer.

    Lines are ``len(text.splitlines())`` summed over every ``*.py`` file
    under the directory (recursive), skipping ``__pycache__``.
    """
    census: dict[str, dict[str, int]] = {}
    for rel in DELIVERY_DIRS:
        files = 0
        lines = 0
        for py in sorted((REPO / rel).rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            files += 1
            lines += len(py.read_text(encoding="utf-8").splitlines())
        census[rel] = {"files": files, "lines": lines}
    return census


def test_AC_meta_delivery_1_census_is_nonvacuous() -> None:
    """Guard non-vacuity (#1416 DoD-addition 1): the scan must see the known set.

    The routers pile is 22 files and the schemas hub 23 at sanction time, so
    a census that sees fewer than 20 / 10 ``*.py`` files (or zero lines) is
    scanning the wrong root, not a thinned repo. If a future dissolution
    genuinely shrinks a directory below the sentinel, lower the sentinel in
    that PR — with the shrunken census in the same diff as evidence.
    """
    census = _delivery_census()
    routers = census["apps/backend/src/routers"]
    schemas = census["apps/backend/src/schemas"]
    assert routers["files"] >= 20 and routers["lines"] > 0, (
        f"sentinel missing: expected >= 20 non-empty *.py files under "
        f"apps/backend/src/routers, saw {routers}; the census is scanning "
        "the wrong root (did routers/ move?)"
    )
    assert schemas["files"] >= 10 and schemas["lines"] > 0, (
        f"sentinel missing: expected >= 10 non-empty *.py files under "
        f"apps/backend/src/schemas, saw {schemas}; the census is scanning "
        "the wrong root (did schemas/ move?)"
    )


def test_AC_meta_delivery_1_delivery_layer_only_thins() -> None:
    baseline: dict[str, int] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    census = {rel: c["lines"] for rel, c in _delivery_census().items()}

    grown = {
        rel: (baseline.get(rel, 0), lines)
        for rel, lines in census.items()
        if lines > baseline.get(rel, 0) + TOLERANCE_LINES
    }
    assert not grown, (
        "the app delivery layer grew — routers/ and schemas/ are sanctioned "
        "for routing and DTO glue only (AC-meta.delivery.1; "
        "migration-standard.md 'The app delivery layer') and their bulk may "
        "only shrink as packages absorb logic. Move domain behavior into the "
        "owning package's base/extension instead. If this growth is genuine "
        "delivery glue (a new endpoint's routing/DTO surface), raise "
        "common/meta/data/delivery-layer-baseline.json in this same PR so the "
        "choice is visible in review.\n"
        f"grown (baseline, actual): {grown}\n"
        f"full census: {json.dumps(census, indent=2)}"
    )

    stale = {
        rel: (expected, census.get(rel, 0))
        for rel, expected in baseline.items()
        if census.get(rel, 0) < expected - TOLERANCE_LINES
    }
    assert not stale, (
        "the baseline over-counts — the delivery layer thinned (good!); "
        "lower common/meta/data/delivery-layer-baseline.json to the new census in "
        "the same PR so the ratchet stays tight and the burndown is "
        "visible.\n"
        f"stale (baseline, actual): {stale}\n"
        f"full census: {json.dumps(census, indent=2)}"
    )
