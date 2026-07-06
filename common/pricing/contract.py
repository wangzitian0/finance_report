"""The ``pricing`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__init__.__all__``
(``implementations["be"]`` = ``apps/backend/src/pricing``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways-cyclic edge.

## What this package is (design review 2026-07-06, #1610)

The price/valuation **observation + resolution** SSOT — not a lookup cache.
Pre-migration, "what is X worth at time T" was scattered across 5 tables with
3 incompatible key vocabularies (``FxRate``, ``StockPrice``,
``MarketDataOverride``, ``ManualValuationSnapshot``, plus statement-extracted
unit prices), and the resolution logic (which observation wins when several
disagree) was implicit and re-derived at each consumption site.

The essence: *an observation that a subject was worth X at time T, from a
source, with an authority rank — plus the resolution policy for conflicting
observations*. NOT named ``market_data`` — the crawler is one source, not the
concept (the package exists even with no crawler: manual valuations and
overrides remain).

## Boundary rulings (record, don't relitigate — see #1610)

1. **Resolution is the core domain service, not an afterthought.**
   ``resolve(subject, as_of, policy)`` — consumers pass policy (reporting
   wants conservative, portfolio wants latest). Moving the 5 tables without
   the resolver would just relocate a junk drawer.
2. **Overrides are append-only high-authority observations, not mutations.**
   Deleting an override re-exposes the prior observation (Axiom A).
   ``MarketDataOverride`` dissolves into the unified observation model
   (``source=manual-override``).
3. **Bitemporal:** ``as_of`` (which day the price belongs to) ≠
   ``observed_at`` (when we learned it). A late backfill must never silently
   rewrite a frozen ``ReportSnapshot``.
4. **Statement-extracted unit prices stay in ``extraction``** (document-fact,
   provenance chain, re-parse lifecycle). ``extraction`` publishes a domain
   event; pricing ingests an id-referenced observation copy
   (``source=statement``). No shared transaction, no FK.
5. **FX splits in two:** conversion *arithmetic* (``convert(money, rate)``,
   rate passed in, pure) stays in ``audit`` — audit never looks up a rate;
   rate *lookup* + FX-specific services (inverse, triangulation, gap
   interpolation) live here.
6. **Subject identity first.** ``PriceableSubject`` unifies the 3 key
   vocabularies (currency pair / listed security / valued component). The
   dual-listing question (same equity, two symbols) is deliberately NOT
   collapsed in the first cut — each listing is its own subject; an alias
   mapping is future package-internal work, not a re-cutover.
7. **Staleness is a fact pricing owns; the tier mapping is policy the
   consumer owns.** ``resolve`` reports an observation's age; reporting
   decides what "too stale" means for its own tier.

``pricing`` is an L3 domain leaf: it imports no other L3 (domain) package —
portfolio/reporting/reconciliation declare the (acyclic, sideways) edge TO
pricing, never the reverse.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="pricing",
    # klass is not declared here — it resolves from PACKAGE_LAYER (L0 owns
    # placement in the five-layer topology, #1595); see
    # common/meta/base/layering.py, which lists pricing as "domain" (L3).
    # Draft until the EPIC-011/005/017 pricing-owned ACs land in `roadmap`.
    status="draft",
    tier=None,
    depends_on=["audit", "platform", "observability", "config"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: the pure observation + subject-identity + policy language ──
        Unit(
            name="PriceObservation",
            kind=Kind.AGGREGATE_ROOT,
            module="base/observation.py",
        ),
        Unit(name="PriceableSubject", kind=Kind.VALUE_OBJECT, module="base/subject.py"),
        Unit(
            name="ObservationSource",
            kind=Kind.VALUE_OBJECT,
            module="base/observation.py",
        ),
        Unit(name="Authority", kind=Kind.VALUE_OBJECT, module="base/observation.py"),
        Unit(name="ResolutionPolicy", kind=Kind.VALUE_OBJECT, module="base/policy.py"),
        Unit(name="PriceObserved", kind=Kind.DOMAIN_EVENT, module="base/events.py"),
        Unit(name="PricingError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        # resolve() is implementation-pure (no I/O — the repository port
        # supplies the candidate observations as a plain argument), but
        # KIND_LAYER places every DOMAIN_SERVICE in extension/ with no
        # exception, so it's placed there physically despite being pure.
        Unit(name="resolve", kind=Kind.DOMAIN_SERVICE, module="extension/resolve.py"),
        # The split block (mechanism B): port in base/, adapter in extension/.
        # The adapter is schema-preserving on purpose — it queries the 4
        # legacy tables (FxRate/StockPrice/MarketDataOverride/
        # ManualValuationSnapshot) directly rather than waiting on a unified
        # physical store, so it can land ahead of that migration.
        Unit(
            name="ObservationRepository",
            kind=Kind.REPOSITORY,
            module="base/repository.py",
            impl="extension/repository.py",
        ),
        # ── extension (reserved): crawlers, manual entry/override write API,
        # FX-specific lookup services, and the extraction event subscriber ──
        Unit(name="sync_market_data", kind=Kind.DOMAIN_SERVICE),
        Unit(name="record_manual_valuation", kind=Kind.DOMAIN_SERVICE),
        Unit(name="record_override", kind=Kind.DOMAIN_SERVICE),
        Unit(name="get_exchange_rate", kind=Kind.DOMAIN_SERVICE),
        Unit(name="ingest_statement_price", kind=Kind.DOMAIN_SERVICE),
        # ── data (reserved): read-models consumed by portfolio/reporting/reconciliation ──
        Unit(name="LatestPriceView", kind=Kind.PROJECTION),
        Unit(name="StalenessView", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/pricing", "fe": None},
    # This commit's real, working surface: the pure base/ model, resolve()
    # (implementation-pure, physically in extension/ per KIND_LAYER), and the
    # repository port + its read-only SQL adapter (querying the 4 legacy
    # tables). The remaining 5 write-side domain-services + 2 data
    # projections are reserved units above — they join the interface once a
    # later commit implements them for real.
    interface=[
        "Authority",
        "ObservationRepository",
        "ObservationSource",
        "PriceObservation",
        "PriceObserved",
        "PriceableSubject",
        "PricingError",
        "ResolutionPolicy",
        "SqlObservationRepository",
        "resolve",
    ],
    events=["PriceObserved"],
    invariants=[
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="converges-by-layer",
            statement="The package converges into base/ (pure) + extension/ (edges) + data/ (projections).",
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_2_converges_by_layer"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement="base/ never imports the package's own extension/ or data/, the ORM, or any network client.",
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_3_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="observations-are-append-only",
            statement=(
                "PriceObservation rows are never updated or deleted in place; an "
                "override is a new higher-authority observation, and removing one "
                "re-exposes the prior observation it superseded (Axiom A)."
            ),
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_4_observations_are_append_only_by_construction"
            ),
        ),
        Invariant(
            id="audit-never-looks-up-a-rate",
            statement=(
                "audit.money.convert takes a rate as an argument and performs no "
                "database lookup; rate lookup lives only in pricing."
            ),
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_5_audit_convert_takes_rate_as_argument"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates pricing with no violations.",
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_6_package_contract_gate_passes"
            ),
        ),
    ],
    # Filled by the EPIC-011/005/017 pricing-AC migration (a later commit in
    # PR1); the package goes status="active" with its authority tier decided
    # there.
    roadmap=[],
)
