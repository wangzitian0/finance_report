# `common/` — the package review surface

`common/` is where the repo's **packages** live as specs and high-level review
surfaces. A package is a DDD bounded context; each one is a directory
`common/<pkg>/` holding its `readme.md` (ubiquitous language), `contract.py` (a
machine-checkable `PackageContract`), and `todo.md` (its worklist).

## Map

Contract-carrying packages, by layer:

- **L0 meta** — [`meta/`](../meta/readme.md): The ``meta`` package's own :class:`PackageContract`.

The package model self-hosts: the meta package that *defines* what a package is
(``PackageContract`` / ``ACRecord`` / ``Invariant`` / ``Unit`` / ``Kind`` and the
``check_package_contract`` gate) is itself a package, with a ``readme.md`` (the
package-model spec), this ``contract.py``, and a ``todo.md``. It is discovered
and validated by the very gate it ships, so the model proves itself.

meta is also the Layout-3 exemplar: it converges into the ``base`` / ``extension``
/ ``data`` layers it governs, and declares its DDD building-block ``units`` (the
``PackageContract`` aggregate root + its value objects in ``base``, the gate as a
``domain-service`` in ``extension``, and ``contract_index`` as a ``projection`` in
``data``). Its BE implementation is ``common/meta`` (the same directory): the
published language is ``common/meta/__init__.py``'s ``__all__``.
- **L1 infra** — [`audit/`](../audit/readme.md): The ``audit`` package's machine-checkable :class:`PackageContract`.

``audit`` is the **number governor** — the parallel peer to ``meta`` (the *form*
governor) in the package migration standard
([`common/meta/migration-standard.md`](../meta/migration-standard.md), the
"meta / audit symmetry"). Where ``meta.base`` is the package model that everyone's
structure conforms to, ``audit.base`` is the **value language** that everyone's
numbers are expressed in: the cross-runtime Shared-Kernel value types
(``Money`` / ``Currency`` / ``ExchangeRate`` / ``MoneyTolerance`` /
``CurrencyBalances`` / ``Ratio`` / ``Quantity`` / ``Unit`` / ``UnitPrice``), plus
audit's own first base value objects: the promotion gate (``InvariantResult`` /
``PromotionDecision`` / ``PromotionVerdict`` / ``evaluate_promotion`` /
``tier_rank``, relocated from ``services/promotion_gate.py`` by #1667). The rest
of audit's own base value objects (confidence / provenance, trace records) still
arrive in a later fold. audit's cross-package numeric-governance reach into the
financial flow (``ledger`` / ``extraction`` / ``portfolio`` / ``reporting``) is
formalized in ``roadmap`` below as ``AC-audit.global-invariant.1``-``.4``
(closeout #1429, umbrella #1416, per the 2026-07-12 scope freeze on #1429):
each id re-homes an already-green, already-existing cross-package test as its
resolving anchor — re-homing proofs, not building a new physical
``audit.extension`` module. The freeze comment's fifth concern (the
traceability-index projection) is already covered by
``AC-reporting.package-traceability.*`` in ``common/reporting/contract.py``,
so it is not duplicated here.

Scope of THIS contract (the physical fold — see ``readme.md`` §Migration state):

* **The four value packages are physically folded into ``audit``.** ``money`` /
  ``ratio`` / ``quantity`` / ``unit_price`` now live as ``common/audit/<domain>``
  + ``apps/backend/src/audit/<domain>`` + ``apps/frontend/src/lib/audit/<domain>``
  (where a frontend mirror exists), each still the canonical cross-runtime
  reference (``conformance/vectors.json`` unchanged in content, only relocated).
  A prior version of this contract argued non-relocation was "the correct
  model" — that was superseded (issue #1419, 2026-07-01): the four packages'
  colliding symbol names (``FloatNotAllowedError`` etc., independently defined in
  every domain) make a flat merge unsafe, so each domain stays an internal
  **submodule** of ``audit`` (``audit.money``, ``audit.ratio``, ...) rather than
  flattening everything into one namespace. Only the 10 non-colliding
  value-object classes are re-exported flat at ``audit``'s root — exactly the
  ``units`` this contract already declared.
* **Pins the number-governor invariants to the existing conformance tests.** Each
  ``invariants[].test`` resolves to a real, already-green conformance/guard test,
  so the gate proves audit's numeric guarantees against the SAME vectors that keep
  the BE/FE mirrors honest — without duplicating or weakening any proof.

The value-language ACs (``AC2.19/2.20`` in EPIC-002, ``AC12.9/12.30/12.32/12.33/
12.36`` in EPIC-012) are homed in ``roadmap`` below as ``AC-audit.<n>.<n>``
(issue #1419 step 2/3, following the physical fold of step 1). Every
``@ac_proof`` edge, docstring/comment cross-reference, and the tier baseline
(``common/meta/data/ac-tier-baseline.json``) were renamed in the same change — no AC
may live in both an EPIC table and a package roadmap (``check_epic_package_dual``
enforces it).

This file is the machine contract the governance gate
(``tools/check_package_contract.py``) validates: ``interface`` == the BE
implementation's ``__all__`` (the 10 value-object classes re-exported flat at
``apps/backend/src/audit/__init__.py``), and every ``invariants[].test`` resolves
to a real test function., [`llm/`](../llm/readme.md): The ``llm`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/llm``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways edge.

## What this package is

The outbound provider abstraction (EPIC-023 → #1426): three orthogonal axes —
protocol family × model × scene — plus the configurable ``scene -> model``
binding, encrypted provider secrets, and the **input-keyed cassette
record/replay mechanism** (cache the model's output by canonicalized input) so
every LLM call is deterministically replayable in CI.

## The two settled boundaries (2026-07-02)

* **runtime classifies, llm implements.** ``runtime`` declares the LLM a
  *model-dominant* external dependency and asserts it is PRESENT (one manifest
  entry + ``LlmCheck``); everything about HOW the app talks to models — scenes,
  bindings, secrets, routing, usage, cassette determinism, and any future
  self-built **evaluation mechanism** — is this package's internal behavior.
  Neither the cassette mechanism nor eval may drift into ``runtime`` or
  ``testing`` (testing owns only fixture DATA + baselines; see
  ``common/testing/contract.py``).
* **Usage statistics are llm-internal.** The ``base`` usage meter emits the
  structured ``llm_usage`` log per call today; the future durable per-user ×
  per-model rollup is a package-internal addition behind the reserved units
  below (``UsageRepository`` port + ``UsageRecorded`` event + the ``data/``
  rollup projection) — never a re-cutover, and never homed in
  ``observability`` (which keeps only the technical OTEL signals).

## No litellm at the package root

The root ``__init__`` exposes the litellm-dependent surface lazily (PEP 562):
``import src.llm`` never imports ``litellm``, so minimal tooling environments
load the package; the dependency is paid on first use of the four lazy names., [`observability/`](../observability/readme.md): The ``observability`` package's machine-checkable :class:`PackageContract`.

``observability`` owns two cohesive surfaces. Its **BE implementation**
(``apps/backend/src/observability``) publishes the backend's observability
language: the vendor-neutral OpenTelemetry runtime contract plus the shared
structured audit/security logging helpers (PII + secret redaction) — this is the
home #1428 relocates the shared logging helpers into. The stdlib OpenPanel query
CLI (``openpanel_query``) stays here in ``common/observability`` as a triage tool
run via ``tools/`` wrappers (its invariant is pinned below).

``depends_on=[]``: the OTEL runtime reads the backend config singleton via its
bare published root (``import src.config``) — but ``src.config`` (the app's
``Settings`` singleton at ``apps/backend/src/config.py``) is not the same thing
as the registered ``config`` *package* (``common/config``, whose real interface
is ``env_keys``/``schema_validation``); this package declares no registered-package
edge for it, since none exists (#1674 corrected this — the two "config"s share a
name, not an identity). The formerly flat ``src.logger`` / ``src.telemetry_metrics``
/ ``src.analytics`` modules, the ``ErrorIds`` vocabulary, and the PII detector
(``pii_redaction``, folded in from ``src.services`` per #1677 — its consumers were
this package's audit helpers and extraction's CSV path) now live inside this
package; its eagerly-imported backend infrastructure remains ``src.config``
only. The package also owns the audit-plane North-Star metric series
(``ConfidenceMetricSnapshot``, ``orm/metrics.py`` — moved from ``src/models``
in #1675 D5); the ORM is published **lazily** so importing the root for
logging never pulls ``src.database``., [`platform/`](../platform/readme.md): The ``platform`` package's machine-checkable :class:`PackageContract`.

``platform`` is the meta layer's *runtime middleware* substrate. Its first
capability is a domain **EventBus implemented via the transactional outbox
pattern**; it also hosts the cross-cutting request **rate limiter** (a
process-global throttle that is request middleware too). It is the technical
substrate logically labelled *middleware* (issue #1427); the package keeps the
name ``platform`` (the existing contract + ACs use it) and treats *middleware* as
the umbrella label. The governance gate
(``tools/check_package_contract.py``) validates the BE implementation
(``apps/backend/src/platform``) against this contract: ``interface`` must equal
the implementation's ``__all__``; every ``invariants[].test`` /
``roadmap[].test`` must resolve to a real test; ``depends_on`` must introduce
no forbidden import edge; and each declared ``unit`` sits in the layer its
``kind`` dictates (``base``/``extension``), with the bus + outbox repository
each split into a base **port** + an extension **adapter**.

### The building-block layering (``units``)

The package converges into ``base`` (pure core) + ``extension`` (impure edges),
mirroring ``counter``. The headline is the **port/adapter split** (mechanism B,
dependency inversion): the ``EventBus`` and ``OutboxRepository`` ports live in
``base`` so the pure core and consumer packages depend only on abstractions,
while their concrete adapters (``OutboxEventBus``/``RecordingEventBus`` and the
SQL ``Outbox`` adapter) live in ``extension``. Because the gate's ``KIND_LAYER``
has no separate "event-bus split" kind, the two ports are modelled with
``kind=REPOSITORY`` (the one base-port/extension-adapter split the gate
recognises); the concrete bus adapters + relay are ``kind=EVENT_BUS`` (extension).
``DomainEvent`` is a base ``domain-event`` record; ``Outbox`` is the entity whose
ORM model lives with the SQL adapter in ``extension`` (declared taxonomy-only, no
placed module, exactly as ``counter`` keeps its ``CounterTally`` table in
``extension``).

### Why layer ``infra``

The layer is a position in the import DAG, not a marketing label. The gate
ranks ``meta(L0) < infra(L1) < middleware(L2) < domain(L3) < app(L4)`` and
forbids any package importing a
target of **equal or higher** rank. ``counter`` (a ``middleware`` package, L2) must
import this package's :class:`DomainEvent` (its ``Incremented`` is a
``DomainEvent``) and write through its bus — a strictly *downward* edge only if
``platform`` (the package) ranks **below** ``counter``. So this foundational
event/outbox + middleware substrate — which declares no governed edges (it
imports only the unregistered ``src.database`` Base/session;
the config-bound ``api_rate_limiter`` instance is wired in ``src.main``) — is placed
in ``infra`` (L1): a leaf the whole app builds events on. "Meta layer" describes its
*role* (the runtime middleware capabilities of the platform substrate);
``infra`` is its honest DAG rank.

### Base ORM mixins + the statement-event-source port (#1675 D6)

``UUIDMixin``/``UserOwnedMixin``/``TimestampMixin`` (``orm/base.py``) moved here
from the dissolved ``src/models/``: pure structural mixins with no business
behavior, imported by every package that owns ORM entities — a natural fit for
an ``infra`` leaf. ``StatementEventSource`` + ``register_statement_reader``
(``extension/workflow_event_builders.py`` / ``extension/workflow_events.py``)
are the same inversion as ``register_uploaded_document_readers`` above:
``extraction`` (L3 domain) owns ``StatementSummary``, so this L1-infra module
may only depend on the plain ``StatementEventSource`` read-model shape,
registered from above by ``main.py`` at startup — never import the ORM class
or its enum types directly., [`runtime/`](../runtime/readme.md): The ``runtime`` package's machine-checkable :class:`PackageContract`.

``runtime`` is the app↔external-world dependency boundary: it owns the *contract*
for the external backends the application depends on (object storage, the LLM
provider, cache, telemetry, …), how each of the six environments substitutes
them, and the invariant that a *declared* dependency must be *asserted present*
(no silent ``skipped``/``warning``/fallback).

An ``infra`` leaf (L1, ``depends_on=[]``), now ``active``. The *construct* phase
shipped the ``base`` value language + dependency manifest + the
``DependencyCheck`` port; the *switch* phase added the ``extension`` probe
adapters (``DatabaseCheck`` / ``ObjectStorageCheck`` / ``LlmCheck``, published
below) that ``boot.Bootloader`` delegates to; the *cleanup* phase dropped the
silent ``skipped`` status. The *migrate* phase homes the smoke-test / health
ACs here: EPIC-008 AC8.1.1–.4 → ``AC-runtime.1.*`` (smoke / service reachability /
DB connectivity) and EPIC-007 AC7.7.1–.2 → ``AC-runtime.7.*`` (``/health``
dependency-presence), each ``test=`` resolving to its existing proof; the package
tier (CODE-ONLY) gives ``proof_kind=exact``; the model-dominant substitute
proofs live with their owning packages (AC-llm.6.2, EPIC-008 AC8.26.*). (Step 3 / cleanup absorbs the
env-smoke-test SSOT prose into ``readme.md`` and retires the doc.) Remaining as a
future feature (not this migration): manifest-driven
``validate`` for *all* declared dependencies per env tier + smoke↔declaration
parity — see ``todo.md``., [`testing/`](../testing/readme.md): The ``testing`` package's machine-checkable :class:`PackageContract`.

``testing`` is an ``infra`` leaf (L1): test/fixture-scoped capability code reused
across backend, tooling, and E2E tests (mirrors ``base_values.py``'s own
docstring: "these helpers are intentionally test/fixture scoped"). It has no
production runtime edge — nothing under ``apps/*/src`` imports it — so unlike
``money``/``counter`` its BE implementation is itself: ``implementations["be"]
= "common/testing"`` (the same self-hosting shape as ``common/meta`` and the
draft ``common/runtime``).

This formalizes what was already a de facto package (50+ test files import
``common.testing.*``) with a machine-checked contract, per the package-model
cutover. It is the landing package for cassette/PDF-fixture test assets: the
32-case LLM cassette corpus (``fixtures/llm_cassettes/`` +
``fixtures/cassette-eval-baseline.jsonl``, ``Cassette`` value object) and the
PDF fixture generator + committed synthetic PDFs (``fixtures/pdf/``,
``FixtureDocument`` value object), both relocated here from
``apps/backend/tests/fixtures/`` / ``tools/_lib/pdf_fixtures/`` and
``docs/ssot/pdf-fixtures.md`` (see ``README.md#pdf-fixtures``).

The package's ACs live here in ``roadmap`` (the package-model AC registry);
``common/meta/extension/generate_ac_registry.py`` sources them directly from this
contract, same as ``counter``. ``roadmap`` groups 1-8 migrated from EPIC-009
(PDF fixture generation, the leading "9" dropped, group/seq preserved:
``AC9.<g>.<s>`` -> ``AC-testing.<g>.<s>``).

EPIC-023's cassette-layer ACs (AC23.5/AC23.6/AC23.7, plus the graded-eval
AC23.8) deliberately do NOT migrate here, even though AC23.5-.7 carry a
``{tier:CODE-ONLY}`` annotation in EPIC-023 prose: this package's own
governance gate (``common/meta/extension/check_authority_reconcile.py``) DETECTS a
package's tier from what its roadmap-AC tests actually exercise, and
``common/meta/extension/authority_classifier.py`` classifies *any* test that
drives the cassette/replay harness as the ``LLM`` band by design (the
harness is inherently LLM-facing infrastructure, not domain-agnostic testing
capability, no matter how deterministic/mocked its assertions are). A
CODE-ONLY package permits zero detected-LLM roadmap-AC tests, so cassette
tests can never be roadmap members here regardless of their EPIC-authored
tier annotation — only the relocated cassette *fixture data*
(``fixtures/llm_cassettes/``) lives in this package; the cassette
*mechanism*'s ACs (and its eventual formal home) stay with ``llm``.
- **L2 middleware** — [`counter/`](../counter/readme.md): The ``counter`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/counter``); every
``invariants[].test`` and ``roadmap[].test`` must resolve to a real test
function; ``depends_on`` must not introduce a forbidden upward/sideways edge.

The package's ACs live here in ``roadmap`` (the package-model AC registry). The
AC-registry generator (``common/meta/extension/generate_ac_registry.py``) sources them
directly from this contract, so they are NO LONGER mirrored into an EPIC table —
the contract is the single source.
- **L3 domain** — [`advisor/`](../advisor/readme.md): The ``advisor`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against.
The implementation physically lives at ``apps/backend/src/advisor`` (#1671
Wave B moved it out of ``apps/backend/src/services/ai_advisor``, absorbing
``services/annualized_income.py``, ``prompts/ai_advisor.py``, and
``models/chat.py`` → ``orm/chat.py``), so the ``interface == __all__`` check
applies. Every ``invariants[].test`` and ``roadmap[].test`` must resolve to a
real test function; ``depends_on`` must not introduce a forbidden
upward/sideways edge.

## What this package is

The application-layer AI financial advisor (EPIC-006 / EPIC-021): a
read-only conversational interface over the user's financial state.  The
advisor **never writes a ledger number** — it only reads from the user's
bounded context (reconciliation readiness, reporting summaries, portfolio
positions) and streams a grounded, cited, disclaimer-tagged response.

## Boundaries (confirmed at cutover, 2026-07-06; physical move 2026-07-12)

* **read-only guardrail** — every write/mutation request (`is_write_request`),
  every prompt-injection attempt (`is_prompt_injection`), and every
  sensitive-data request (`is_sensitive_request`) is refused before any LLM
  call is made.  The guardrail is also applied on the streaming path via
  `StreamRedactor`.  This is the package's non-negotiable invariant.
* **bounded context** — the advisor reads reconciliation/reporting/portfolio
  data as part of the same read-only request (the same `AsyncSession` as the
  chat-message insert — ``AC-advisor.txn.1``, now ``done``: every
  cross-domain read goes through the target package's *published* root
  (``ledger``/``platform``/``portfolio``/``pricing``/``reconciliation``/
  ``reporting``), and the one read whose owner still lives in the app
  remainder (the fx-pair composer; windowed fx conversion for the
  annualized-income schedule) is injected through ``extension/app_reads.py``
  by the composition root — never a direct ``src.services.*`` import, never
  a cross-domain FK).  It never *writes* into the ledger.
* **LLM via ``llm``** — all provider calls go through the ``llm`` package
  (`SceneBinding` / `stream_ai_chat`); the advisor owns no raw HTTP surface.
* **session ownership** — a `ChatSession` is owned by exactly one user;
  once a session is closed it is immutable (the ARCHIVED lifecycle is a
  planned addition — `AC-advisor.session.1`).

## Cross-domain read edges

``depends_on`` mirrors the real import set: ``audit`` (money formatting),
``ledger`` (Account/AccountType/journal-line reads for the annualized-income
schedule and category context — registered as advisor's dependency once
#1675's D5 omnibus moved account.py/journal.py into ``ledger``, mid-flight of
this PR), ``llm`` (scene binding + streaming transport), ``observability``
(logging), ``platform`` (workflow status, HTTP error helpers), ``portfolio``
(summary, active symbols), ``pricing`` (market-data status),
``reconciliation`` (stats), ``reporting`` (balance sheet, income statement,
category breakdown, report-package readiness, income bucket classifier —
folded from the app remainder by #1666 while this PR was in flight).  All are
*read-only* edges; the advisor never writes into them.  The observed-FX-pair
composer is the
one remaining app-remainder read: its owner (``services/market_data_
scheduler.py``) hasn't folded yet (#1610), so the advisor consumes it
through the ``app_reads`` injection port; the edge gets declared when the
fold lands and the port collapses into a published-root import.  ``config``
was folded into ``runtime`` (#1669) — the flat ``src.config`` module is
shared infra, imported as the bare root.

## God-file → phase split (follow-up scope)

``extension/service.py`` (~860 lines) is still to be split into
``phases/{context_aggregation,prompt_construction,response_streaming}.py``;
``base/guardrails.py`` is already separate.  Until then the units are
declared *taxonomy-only* (``module=None``): the governance gate skips
placement checks for units without a module path, per the package model., [`extraction/`](../extraction/readme.md): The ``extraction`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__init__.__all__``
(``implementations["be"]`` = ``apps/backend/src/extraction``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways edge.

## What this package is

The statement-parsing bounded context (EPIC-003/EPIC-013 → #1421): documents
in (PDF/image/CSV), verified financial facts out. It owns the **source→fact**
half of the money pipeline — parsing (vision-LLM + per-institution CSV),
per-currency balance closure and balance-chain continuity, dedup by content
hash, brokerage detection/positions, and the evidence lineage that links every
extracted fact to its source document.

## Ownership boundaries

* **AtomicTransaction is extraction's aggregate**: downstream domains
  (reconciliation / reporting) reference its rows **by id** (Decision B) —
  the Stage-4 parallelism anchor.
* ``UploadedDocument`` moved from the unregistered ``src/models/`` into
  ``orm/layer1.py`` (#1675 D3); its ``platform``/``runtime`` readers now go
  through the published ``extension/uploaded_document_reads.py`` lookups
  instead of importing the ORM class. The rest of the fact family followed in
  D4+D5c (``orm/layer2-4.py``, ``orm/evidence.py``, ``orm/correction.py``)
  after every cross-domain ``relationship()`` (to ``Account``/``User``) was
  replaced by bare FK id columns + explicit reads; downstream domains import
  the published entity names. ``portfolio`` left ``depends_on`` in the same
  step: the one extraction→portfolio call (position reconciliation after a
  brokerage import) is inverted through ``register_position_reconciler``,
  wired by ``main.py``, so portfolio can import this package's entities
  without a cycle. ``StatementSummary``/statement enums completed the move in
  #1675 D6 (``orm/statement_summary.py`` / ``orm/statement_enums.py``), the
  final models-decentralization slice: their three cross-domain readers each
  needed the same inversion — ``platform`` (L1-infra, upward) reads through
  the registered ``StatementEventSource`` port, and ``ledger``/``identity``
  (same rank, dependency-cycle — both readers extraction itself
  ``depends_on``) read through their own registered ports
  (``register_statement_coverage_reader`` / ``register_in_flight_parse_checker``),
  each wired by ``main.py``, mirroring ``register_uploaded_document_readers``
  above.
* ``confidence_metric`` / ``confidence_tier`` (journal-confidence metric
  snapshots) are NOT this package's — they read ledger's aggregates and stay
  in ``services/`` pending the reporting/observability re-home.
* The OCR layout-parsing call routes through ``src.llm``'s ``ocr_layout_call``
  chokepoint (#1670), which is why ``llm`` is now a declared dependency. The
  JSON/vision call sites already went through ``llm`` via
  ``src.llm``'s ``stream_ai_json`` (physically ``llm/extension/streaming.py``
  since #1670's fold). Threading per-user provider binding (``user_id``)
  into these OCR/vision/json call sites — so a BYO-provider user's own model
  is used, not just the deployment default — is a separate, still-pending
  follow-up (AC-llm.4.5), independent of the ``llm`` dependency edge itself., [`identity/`](../identity/readme.md): The ``identity`` package's machine-checkable :class:`PackageContract`.

``identity`` is the vertical **users + authentication + AI-feedback** domain slice
(layer ``domain``, L3 — resolved from the central map in
``common/meta/base/layering.py``). The governance gate (``tools/check_package_contract.py``)
validates the BE implementation (``apps/backend/src/identity``) against this
contract: ``interface`` must equal the implementation's ``__all__``; every
``invariants[].test`` / ``roadmap[].test`` must resolve to a real test;
``depends_on`` must introduce no forbidden import edge (a ``domain`` package may
import the ``infra`` substrate it builds on — ``platform`` for the rate limiter,
``observability`` for the security-warning log — both strictly downward); and each
declared ``unit`` sits in the layer its ``kind`` dictates.

### The building-block layering (``units``)

The package converges into ``base`` (pure core) + ``extension`` (impure edges),
mirroring ``counter``/``platform``:

- **base** — the auth/AI-feedback value objects (``RegisterRequest``/``LoginRequest``/
  ``AuthResponse`` and the AI-feedback request/response shapes), the canonical-key
  helpers (``normalize_email``/``AUTH_COOKIE_NAME``), and the ``UserRepository``
  *port*. The ``User`` aggregate root and its ``AiFeedback`` child entity are
  declared here taxonomy-only (no placed module): their ORM models live with the
  SQL adapter in ``extension`` (exactly as ``counter`` keeps ``CounterTally`` and
  ``platform`` keeps ``Outbox`` in ``extension``), so ``base`` stays free of the ORM.
- **extension** — the impure edges: the SQL ``UserRepository`` adapter (the
  port/adapter split, mechanism B), the JWT + bcrypt security domain services, the
  ``get_current_user_id`` auth dependency, the ``register``/``login`` domain
  operations, the auth rate limiters, the observability binding, and the ``/auth``
  + ``/users`` transport (``extension/api/``).

### Why layer ``domain``

``User``/``AiFeedback`` are a vertical domain (a bounded context), not a reusable
horizontal capability — so identity is a ``domain`` package. The gate ranks
``meta(L0) < infra(L1) < middleware(L2) < domain(L3) < app(L4)`` and forbids
importing an equal/higher rank; identity (``domain``) importing
``platform``/``observability`` (``infra``) is a strictly downward edge.

The package's ACs live here in ``roadmap`` (the package-model AC registry),
sourced directly into the AC registry — no longer mirrored into the EPIC-001
table (the rows are removed there with a disclaimer pointing here)., [`ledger/`](../ledger/readme.md): The ``ledger`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/ledger``); every
``invariants[].test`` resolves to a real test function; ``depends_on`` must not
introduce a forbidden upward/sideways edge; and the building-block layering holds
(``base`` pure, each unit in its ``kind``'s layer, the ``JournalRepository`` split
into a base port + extension adapter, the account-balance projection a ``data``
sink).

``ledger`` is the first ``domain``-layer (L3) bounded context on the package
model (the double-entry bounded context). Slice 3b (#1420) folds the **processing (in-transit) account**
into the package: its pure identity + transfer detection/scoring policy live in
``base/processing.py`` (the :class:`ProcessingAccount` aggregate + ``TransferPair``
value object + ``detect_transfer_pattern``) and its impure verbs (acquire / post /
project / ``find_transfer_pairs``) in ``extension/processing.py`` — the original
``services/processing_account.py`` is deleted (zero residue). Reconciliation/
reporting consume it only through the published ``src.ledger`` interface, by id/
event (Decision B — one transaction per domain).

The package's ACs migrate into ``roadmap`` across the slice-3c sub-slices of the
cutover (#1420). **Slice 3c-i homed the EPIC-015 processing-account ACs** as
``AC-ledger.71.* … AC-ledger.76.*``. **Slice 3c-ii homed the first half of the
EPIC-002 double-entry core** — groups ``AC2.1``…``AC2.12`` → groups
``AC-ledger.1.*``…``AC-ledger.12.*`` (the leading "2" is dropped; seq preserved).
**Slice 3c-iii (this change, the final AC batch) homes the genuine double-entry
ACs of the second half** — ``AC2.13``…``AC2.16`` → groups
``AC-ledger.13.*``…``AC-ledger.16.*`` (same drop-the-"2", seq-preserved rule). It
deliberately does **not** drag the non-double-entry rows of that range into the
ledger roadmap (the #1517 mis-file lesson — validate each AC, never blanket
rename): the frontend UI ACs ``AC2.15.8``/``AC2.16.3``/``AC2.17.1`` stay in
EPIC-002 (ledger is ``fe=None``), the reporting tier-degrade ``AC2.16.4`` is a
report-layer property not a posting one, the framework-boundary contract
``AC2.18.1`` is a cross-EPIC doc-assertion test (not double-entry behaviour), and
the entire Money value-type extension ``AC2.19.*``–``AC2.23.*`` belongs to the
``audit`` package (``infra``-layer; folded from ``money`` — issue #1419), not ledger. Those rows
remain defined in EPIC-002.
In each case the package now owns the migrated ACs; the source EPIC backend
tables are deleted and replaced with a disclaimer that lists the new ids
(mirroring how identity emptied EPIC-001).

**Group-number reservation (ledger-local).** The first dotted segment of an
``AC-ledger.<group>.<seq>`` id is a bare uniqueness key (no gate reads semantics
from it), so the package reserves disjoint blocks to keep the namespace
collision-free as later slices add ACs without re-reading this file:

- **groups 1–12** — the EPIC-002 double-entry core, first half (slice 3c-ii)
  (1=account-mgmt, 2=entry-creation, 3=posting/voiding, 4=balance, 5=equation,
  6=boundary, 7=router/errors, 8=decimal-safety, 9=data-model, 10=endpoints,
  11=must-have-traceability, 12=multi-currency), each mirroring its source
  ``AC2.<g>`` group;
- **groups 13–16** — the genuine double-entry ACs of the EPIC-002 second half
  (slice 3c-iii, this change): 13=user-scoped ledger integrity,
  14=database invariant floor, 15=guided opening balances,
  16=opening-balance readiness, each mirroring its source ``AC2.<g>`` group (only
  the backend double-entry rows; the frontend/reporting/framework/money rows of
  ``AC2.15``–``AC2.23`` stay in EPIC-002 as noted above);
- **groups 17–70** — reserved for any later EPIC-002/012 double-entry ACs (not
  yet homed);
- **groups 71–76** — the EPIC-015 processing (in-transit) account, slice 3c-i
  (71=creation, 72=transfer-entry, 73=integrity, 74=detection, 75=scoring,
  76=reconciliation integration), each mirroring its source ``AC15.<g>`` group.

(The aspirational ``AC-ledger.<entity>.<seq>`` form some docs advertise is not
adopted: the live traceability regex in
``common/testing/ac_traceability_refs.py`` accepts only the numeric
``AC-<pkg>.<n>.<n>`` grammar that every shipped package — counter/authority/
identity — already uses.) The EPIC-015 **frontend** UI-gap ACs (``AC15.7.*``)
stay in EPIC-015: ledger is a backend-only package (``fe=None``), exactly as the
identity migration left EPIC-001's frontend rows in place. ``roadmap`` carries the
homed backend ACs (the 23 EPIC-015 processing ACs + the 61 EPIC-002 first-half
ACs + the 18 EPIC-002 second-half double-entry ACs of slice 3c-iii); the
structural invariants of the cutover stay in ``invariants`` (no tier, not
matrix-constrained). Decision A — standard-preserving move, no bar lowered., [`portfolio/`](../portfolio/readme.md): The ``portfolio`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__init__.__all__``
(``implementations["be"]`` = ``apps/backend/src/portfolio``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways-cyclic edge.

## What this package is (issue #1422, Stage 3 of umbrella #1416)

Investment position accounting: buy/sell/dividend transactions posted through
``ledger.post_entry``, ``ManagedPosition``/``InvestmentLot`` bookkeeping
(cost-basis method, FIFO/LIFO/AVGCOST lot consumption), and the read-side
holdings/P&L/allocation/performance queries built on top.

**Positions-only boundary** (2026-07-06, updated after the pricing design
review #1610): portfolio owns only position math — quantity, cost basis,
realized/unrealized P&L. It never fetches or stores a price or a valuation;
it *consumes* one via ``pricing.resolve(subject, as_of, policy)``. The old
``MarketDataOverride`` write path (``PortfolioService.update_market_prices``)
belongs to ``pricing.record_override`` now, not here — see the P3 unit note
below for how that overlap is resolved.

## Ownership boundaries

* **``ManagedPosition`` is portfolio's aggregate**: it owns ``InvestmentLot``
  and ``InvestmentTransaction``; the invariant is *open position quantity ≥ 0*
  plus cost-basis consistency across lots.
* The ORM entities: ``InvestmentLot``/``InvestmentTransaction``/
  ``DividendIncome`` live in this package's own ``orm/portfolio.py``
  (#1675 D5); ``ManagedPosition``/``AtomicPosition`` live in ``extraction``'s
  ``orm/layer3.py`` (#1675 D4+D5c — extraction owns the fact family's ORM;
  portfolio imports the published entities, never the ORM class directly).
  Their enums (``PositionStatus``/``CostBasisMethod``/
  ``InvestmentTransactionType``/``DividendType``) are declared alongside them
  on the ORM model files, so they're taxonomy-only here too.
* Cross-package edges today (updated at the #1641/#1643 read-side cutover):
  ``audit`` (Money/Quantity/UnitPrice base types), ``ledger`` (``post_entry``
  — portfolio writes only its own aggregate in one transaction, then posts a
  balanced ``Entry``; no shared transaction), ``observability`` (logging),
  and ``pricing`` (the published FX surface ``convert_amount``/``convert_money``
  with the ``lazy_load`` crawler fallback, plus ``StockPrice``/
  ``MARKET_DATA_QUANTITY_UNIT`` — portfolio consumes prices, never fetches or
  stores one). ``platform`` (event publish) is still intent, not code — add it
  to ``depends_on`` with its first real import, not before (a
  declared-but-unused edge fails ``check_package_contract`` as of #1674)., [`pricing/`](../pricing/readme.md): The ``pricing`` package's machine-checkable :class:`PackageContract`.

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
pricing, never the reverse., [`reconciliation/`](../reconciliation/readme.md): The ``reconciliation`` package's machine-checkable :class:`PackageContract`., [`reporting/`](../reporting/readme.md): The ``reporting`` package's machine-checkable :class:`PackageContract`.

This contract records the reporting-domain cutover boundary for Stage 4 of the
package migration umbrella (#1416, issue #1424): reporting is the
calculation-over-ledger package, declares its building blocks with
``units=[Unit(kind=...)]``, and — since the #1666 physical fold — implements
at ``apps/backend/src/reporting/{base,extension,data}``.

Scope correction (2026-07-06): ``manual_valuation.py`` belongs to the pricing
cutover (#1610). Reporting keeps confidence-tier mapping and report assembly;
pricing owns valuation-observation staleness facts. Pending that cutover,
reporting reaches manual valuation and the FX conversion service through
composition-root-injected ports (``register_manual_valuation_lines_provider``
/ ``register_fx_gateway``), never by importing the ``services/`` remainder.

Status flip (migration closeout wave 2, #1663): the roadmap's first ACs
(opening-balance gate + the full EPIC-020 framework-reporting set) carry only
``proof_kind`` in ``{exact, property}``, both valid under ``CODE-ONLY`` — so
the package ships ``active``/``CODE-ONLY`` here.

#1674 contract-honesty audit (2026-07-09): declare a dependency only with its
first real import. ``extraction`` gained one in the #1666 fold
(``report_traceability`` reads the evidence graph through the published
``EvidenceLineageService``); ``config``/``platform`` remain undeclared until
a real import exists.
- **L4 app** — [`ui_core/`](../ui_core/readme.md): ui_core
