"""The ``identity`` package's machine-checkable :class:`PackageContract`.

``identity`` is the vertical **users + authentication + AI-feedback** domain slice
(``klass="core"``). The governance gate (``tools/check_package_contract.py``)
validates the BE implementation (``apps/backend/src/identity``) against this
contract: ``interface`` must equal the implementation's ``__all__``; every
``invariants[].test`` / ``roadmap[].test`` must resolve to a real test;
``depends_on`` must introduce no forbidden import edge (a ``core`` package may
import the ``kernel`` substrate it builds on — ``platform`` for the rate limiter,
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

### Why ``klass="core"``

``User``/``AiFeedback`` are a vertical domain (a bounded context), not a reusable
horizontal capability — so identity is a ``core`` package. The gate ranks
``kernel(0) < platform(1) < core(2)`` and forbids importing an equal/higher rank;
identity (``core``) importing ``platform``/``observability`` (``kernel``) is a
strictly downward edge.

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
    # Downward edges only: the kernel substrate identity builds on — the platform
    # rate limiter, the observability security-warning log, and config (settings,
    # imported by its bare published root like observability does). All three are
    # kernel-class, so a core package importing them is strictly downward.
    # (src.database / src.deps are unregistered backend infra, out of scope for
    # the edge rule; the former flat src.logger / src.utils now live inside the
    # observability / platform packages, so those imports are governed edges.)
    depends_on=["platform", "observability", "config"],
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
        "LoginRequest",
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
        "login",
        "normalize_email",
        "oauth2_scheme",
        "register",
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
    ],
)
