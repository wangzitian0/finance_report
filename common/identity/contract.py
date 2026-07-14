"""The ``identity`` package's machine-checkable :class:`PackageContract`.

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
table (the rows are removed there with a disclaimer pointing here).
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="identity",
    status="active",
    # Deterministic auth/user domain, no LLM: a pure-code (CODE-ONLY) package.
    # Every AC in the roadmap inherits this tier.
    tier="CODE-ONLY",
    # Downward edges only: the infra substrate identity builds on — the platform
    # rate limiter, the observability security-warning log, and config (settings,
    # imported by its bare published root like observability does). All three are
    # infra-class, so a domain package importing them is strictly downward.
    # (src.database / src.deps are unregistered backend infra, out of scope for
    # the edge rule; the former flat src.logger / src.utils now live inside the
    # observability / platform packages, so those imports are governed edges.)
    depends_on=["platform", "observability"],
    roles=["base", "extension"],
    units=[
        # base — the auth value objects (the published wire language).
        Unit(
            name="RegisterRequest", kind=Kind.VALUE_OBJECT, module="base/types/auth.py"
        ),
        Unit(name="LoginRequest", kind=Kind.VALUE_OBJECT, module="base/types/auth.py"),
        Unit(name="AuthResponse", kind=Kind.VALUE_OBJECT, module="base/types/auth.py"),
        # base — the AI-feedback value objects (the AiFeedback entity's wire language).
        Unit(
            name="AiFeedbackRequest",
            kind=Kind.VALUE_OBJECT,
            module="base/types/ai_feedback.py",
        ),
        Unit(
            name="AiFeedbackResponse",
            kind=Kind.VALUE_OBJECT,
            module="base/types/ai_feedback.py",
        ),
        # base — the User aggregate root + the AiFeedback child entity. Their ORM
        # models live with the SQL adapter in extension/ (like counter's
        # CounterTally / platform's Outbox), so they are declared taxonomy-only
        # (no placed module) to keep base/ free of the ORM. The aggregate's
        # invariant (email unique case-insensitively) is enforced by the
        # uq_users_email_normalized index in extension/sql.py.
        Unit(name="User", kind=Kind.AGGREGATE_ROOT),
        Unit(name="AiFeedback", kind=Kind.ENTITY),
        # repository — the one split block (mechanism B): the abstract port lives
        # in base/, the SQL adapter in extension/ (dependency inversion).
        Unit(
            name="UserRepository",
            kind=Kind.REPOSITORY,
            module="base/repository.py",
            impl="extension/sql.py",
        ),
        # extension — the security domain services (JWT + bcrypt).
        Unit(
            name="create_access_token",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/security.py",
        ),
        Unit(
            name="decode_access_token",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/security.py",
        ),
        Unit(
            name="hash_password",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/security.py",
        ),
        Unit(
            name="verify_password",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/security.py",
        ),
        # extension — the auth dependency + the register/login domain operations.
        Unit(
            name="get_current_user_id",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/auth.py",
        ),
        Unit(name="register", kind=Kind.DOMAIN_SERVICE, module="extension/api/auth.py"),
        Unit(name="login", kind=Kind.DOMAIN_SERVICE, module="extension/api/auth.py"),
        # extension — the observability request-context binding.
        Unit(
            name="bind_authenticated_user_context",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/observability.py",
        ),
        # extension — the test/QA account-purge maintenance service (folded in
        # from src/services per #1677: purging user accounts + their owned rows
        # is user-lifecycle administration, and its one domain import is User).
        Unit(
            name="purge_test_accounts",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/account_purge.py",
        ),
        # PurgeReport is declared taxonomy-only (no placed module) like
        # User/AiFeedback: it is defined next to the purge service in
        # extension/account_purge.py rather than base/, keeping the dataclass
        # beside the only code that constructs it.
        Unit(name="PurgeReport", kind=Kind.VALUE_OBJECT),
    ],
    implementations={"be": "apps/backend/src/identity", "fe": None},
    interface=[
        "AUTH_COOKIE_NAME",
        "AiFeedback",
        "AiFeedbackRequest",
        "AiFeedbackResponse",
        "AiSuggestionListResponse",
        "AiSuggestionResponse",
        "AuthResponse",
        "DEFAULT_TEST_EMAIL_PATTERN",
        "LoginRequest",
        "PurgeReport",
        "RegisterRequest",
        "User",
        "UserRepository",
        "auth_rate_limiter",
        "auth_router",
        "bind_authenticated_user_context",
        "create_access_token",
        "decode_access_token",
        "get_current_user_id",
        "get_me",
        "hash_password",
        "is_safe_purge_environment",
        "login",
        "normalize_email",
        "oauth2_scheme",
        "purge_test_accounts",
        "register",
        "register_in_flight_parse_checker",
        "register_rate_limiter",
        "users_router",
        "verify_password",
    ],
    events=[],
    invariants=[
        # Structural guarantees (no authority tier, not matrix-constrained) — the
        # building-block layering this cutover establishes. See counter/platform.
        Invariant(
            id="converges-by-layer",
            statement="The package converges into base/ (pure core) + extension/ (edges).",
            test=(
                "tests/tooling/test_identity_package.py"
                "::test_identity_converges_by_layer"
            ),
        ),
        Invariant(
            id="single-home-no-residue",
            statement=(
                "The pre-migration god-files (src/auth.py, src/security.py, "
                "src/rate_limit.py, src/observability_events.py, src/routers/auth.py, "
                "src/routers/users.py, src/schemas/auth.py, src/schemas/ai_feedback.py, "
                "src/models/user.py) are deleted — identity is the single home."
            ),
            test=(
                "tests/tooling/test_identity_package.py"
                "::test_identity_god_files_are_gone"
            ),
        ),
        Invariant(
            id="repository-split",
            statement=(
                "The UserRepository port splits into a base port + an extension SQL "
                "adapter (dependency inversion, mechanism B)."
            ),
            test=(
                "tests/tooling/test_identity_package.py::test_identity_repository_split"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement=(
                "The base/ layer never imports the package's own extension/ layer."
            ),
            test=(
                "tests/tooling/test_identity_package.py"
                "::test_identity_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_identity_package.py"
                "::test_identity_interface_equals_published_language"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates identity with no violations.",
            test=(
                "tests/tooling/test_identity_package.py"
                "::test_identity_package_contract_gate_passes"
            ),
        ),
    ],
    roadmap=[
        ACRecord(
            id="AC-identity.1.1",
            statement=(
                "Email identity is unique case-insensitively: a duplicate "
                "registration in any case variant is rejected (the normalized-email "
                "index makes a duplicate unrepresentable). Was EPIC-001 AC1.7.2 / "
                "AC1.10.2."
            ),
            test=(
                "apps/backend/tests/identity/test_auth_router.py"
                "::test_register_duplicate_email"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.1.2",
            statement=(
                "Case-variant email is normalized on registration and login so case "
                "variants cannot create or split a duplicate account. Was EPIC-001 "
                "AC1.10.2."
            ),
            test=(
                "apps/backend/tests/identity/test_auth_router.py"
                "::test_AC1_10_2_register_rejects_case_variant_duplicate_email"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.2.1",
            statement=(
                "Registration accepts a valid payload, bcrypt-hashes the password "
                "(plaintext is never stored), and returns a JWT + HttpOnly cookie. "
                "Was EPIC-001 AC1.5.5 / AC1.7.1."
            ),
            test=(
                "apps/backend/tests/identity/test_auth_router.py::test_register_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.2.2",
            statement=(
                "Login accepts valid credentials and returns a JWT + HttpOnly cookie; "
                "invalid credentials are rejected. Was EPIC-001 AC1.5.5 / AC1.7.3."
            ),
            test=(
                "apps/backend/tests/identity/test_auth_router.py::test_login_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.2.3",
            statement=(
                "Registration handles the duplicate-email IntegrityError race "
                "(concurrent registrations of the same email) with a clean 400. Was "
                "EPIC-001 AC1.7.4."
            ),
            test=(
                "apps/backend/tests/identity/test_auth_router.py"
                "::test_register_integrity_error_race_condition"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.2.4",
            statement=(
                "A valid JWT bearer token grants 200 on a protected endpoint "
                "(GET /accounts). Was EPIC-001 AC1.2.2 (migration closeout wave "
                "3, #1663)."
            ),
            test="apps/backend/tests/identity/test_auth.py::test_auth_valid_user",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.2.5",
            statement=(
                "The auth dependency accepts the HttpOnly session cookie directly "
                "(no bearer header required) for GET /auth/me. Was EPIC-001 "
                "AC1.10.3 (migration closeout wave 3, #1663); the row's frontend-"
                "storage half stays in the EPIC (no backend package home)."
            ),
            test=(
                "apps/backend/tests/identity/test_auth_router.py"
                "::test_AC1_10_3_get_me_accepts_httponly_cookie"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.1.3",
            statement=(
                "The /users management endpoints expose authenticated current-user "
                "operations without cross-user leakage (a non-self user_id returns "
                "not-found). Was EPIC-001 AC1.8.1."
            ),
            test=(
                "apps/backend/tests/identity/test_users_router.py"
                "::test_AC1_8_1_get_user_by_id_hides_other_users"
            ),
            priority="P1",
            status="done",
        ),
        # ── group journeys: E2E auth/session proof (migrated from EPIC-008
        # AC8.2.1/.7.1-3/.19.2, migration closeout continuation, #1663) ──
        ACRecord(
            id="AC-identity.journeys.1",
            statement="A new user can register and log in end to end through the deployed API.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_register_and_login_flow",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.journeys.2",
            statement=(
                "API authentication failures (missing/invalid credentials) return a "
                "clean 401/422, not a 500."
            ),
            test="apps/backend/tests/e2e/test_core_journeys.py::test_api_authentication_failures",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.journeys.3",
            statement="Unauthenticated requests to protected endpoints are blocked with 401.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_unauthorized_access_blocked",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-identity.journeys.4",
            statement="A user's session (JWT/cookie) is created, reused, and honored consistently across requests.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_user_session_management",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.journeys.5",
            statement=(
                "The frontend registration E2E targets the mode-toggle register control "
                "by test id and switches into register mode without a strict-mode "
                "locator failure."
            ),
            test="tests/e2e/test_auth_flows.py::test_full_registration_flow",
            priority="P1",
            status="done",
        ),
        # ── purge: test/QA account-purge maintenance (was EPIC-008 AC8.17,
        # folded in with extension/account_purge.py per #1677 / #1663 wave 3) ──
        ACRecord(
            id="AC-identity.purge.1",
            statement=(
                "Only disposable test accounts (qa/e2e/load-test prefixes on "
                "example.com / test.example.com) are selected for purging; real "
                "accounts and plain local fixtures are excluded, and the users "
                "table itself is never in the owned-tables delete list. Was "
                "EPIC-008 AC8.17.1."
            ),
            test=(
                "apps/backend/tests/identity/test_account_purge.py"
                "::test_selection_matches_test_accounts_and_excludes_real_ones"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.purge.2",
            statement=(
                "Applying the purge removes a clean test account and every row "
                "it owns, while leaving non-test accounts untouched. Was "
                "EPIC-008 AC8.17.2."
            ),
            test=(
                "apps/backend/tests/identity/test_account_purge.py"
                "::test_apply_purges_clean_account_and_leaves_others"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.purge.3",
            statement=(
                "An account owning a posted (immutable) ledger entry is reported "
                "blocked and fully preserved, never force-deleted — mirroring "
                "the 409 the API returns. Was EPIC-008 AC8.17.3."
            ),
            test=(
                "apps/backend/tests/identity/test_account_purge.py"
                "::test_account_with_posted_ledger_entry_is_blocked_not_deleted"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.purge.4",
            statement=(
                "A dry run names the accounts it would purge but persists no "
                "deletions. Was EPIC-008 AC8.17.4."
            ),
            test=(
                "apps/backend/tests/identity/test_account_purge.py"
                "::test_dry_run_reports_but_persists_nothing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.purge.5",
            statement=(
                "The CLI --apply environment guard allows dev/staging/CI and "
                "refuses production (or an unset environment) without an "
                "explicit override. Was EPIC-008 AC8.17.5."
            ),
            test=(
                "apps/backend/tests/identity/test_account_purge.py"
                "::test_environment_guard_allows_dev_staging_and_refuses_production"
            ),
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ACRecord(
            id="AC-identity.fe-auth.1",
            statement="`getUserId` returns `null` when not set",
            # was AC16.5.1
            test="apps/frontend/src/__tests__/auth.test.ts::AC16.5.1/AC16.5.2 returns null when key is not set",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.2",
            statement="`getUserId` returns stored `userId` from `localStorage`",
            # was AC16.5.2
            test="apps/frontend/src/__tests__/auth.test.ts::AC16.5.2 returns stored userId from localStorage",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.3",
            # Corrected from the stale EPIC-016 row text (#1821 Wave B CR fix):
            # the real current behavior never persists a bearer token -- the
            # login response's token is explicitly cleared/dropped, not stored.
            statement=(
                "`setUser` stores `userId` and `email` in `localStorage`; it "
                "never persists a bearer token, even when the caller provides "
                "one (a stale token is actively cleared)"
            ),
            # was AC16.5.3
            test="apps/frontend/src/__tests__/auth.test.ts::AC16.5.3 stores userId and email",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.4",
            statement="`clearUser` removes all auth keys from `localStorage`",
            # was AC16.5.4
            test="apps/frontend/src/__tests__/auth.test.ts::AC16.5.4 removes all auth keys from localStorage",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.5",
            # Corrected from the stale EPIC-016 row text (#1821 Wave B CR fix):
            # isAuthenticated checks a stored userId session marker, not a
            # token; anchored to the true-case test per the statement's claim.
            statement=(
                "`isAuthenticated` returns `true` when a local session marker "
                "(userId) is stored, `false` when none exists"
            ),
            # was AC16.5.5
            test="apps/frontend/src/__tests__/auth.test.ts::AC16.5.5 returns true when non-secret user session metadata exists",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.6",
            statement="Login page submits login payload and redirects on success",
            # was AC16.12.5
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.5 AC22.1.3 submits login payload and redirects to Home",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.7",
            statement="Login page toggles register mode and switches endpoint for submit",
            # was AC16.12.6
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.6 switches to register mode and uses register endpoint",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.8",
            statement="Login page shows API error messages and resets loading state on failure",
            # was AC16.12.7
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.7 shows API error and exits loading state",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.9",
            statement="Toggles password visibility",
            # was AC16.12.13
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.13 toggles password visibility",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.10",
            statement="Shows error with alert role and aria-live",
            # was AC16.12.14
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.14 shows error with alert role and aria-live",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.11",
            statement="Shows mode toggle links",
            # was AC16.12.15
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.15 shows mode toggle links",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.12",
            statement="Shows loading spinner during submission",
            # was AC16.12.16
            test="apps/frontend/src/__tests__/loginPage.test.tsx::AC16.12.16 shows loading spinner during submission",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.13",
            statement="App shell renders workspace providers and main content with collapse-aware layout",
            # was AC16.19.1
            test="apps/frontend/src/__tests__/shellAndAuth.test.tsx::AC16.19.1 renders providers and collapse-aware shell layout",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-identity.fe-auth.14",
            statement="Auth guard redirects unauthenticated protected routes and allows public routes",
            # was AC16.19.2
            test="apps/frontend/src/__tests__/shellAndAuth.test.tsx::AC16.19.2 redirects unauthenticated protected routes",
            priority="P2",
            status="done",
        ),
    ],
)
