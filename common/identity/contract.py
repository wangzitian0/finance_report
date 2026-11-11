"""Machine-checkable PackageContract for ``identity``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="identity",
    status="active",
    tier="CODE-ONLY",
    depends_on="platform observability".split(),
    roles="base extension".split(),
    implementations={"be": "apps/backend/src/identity", "fe": None},
    context=ContextScope(
        purpose="Own user identity, authentication, user-scoped credentials.",
        in_scope=[
            "User aggregate, normalized email identity, and AI-feedback records.",
            "JWT/OAuth authentication, password security, and current-user resolution.",
            "Identity-owned registration, login.",
        ],
        out_of_scope=[
            "Ledger, statement, portfolio, reporting, or reconciliation state and policy.",
            "Generic request limiting, HTTP error vocabulary, or persistence substrate ownership.",
            "Cross-domain workflow or application-level authorization decisions.",
        ],
    ),
    relationships=rels(
        "identity",
        """
platform|consumer-port|Consumes platform rate-limiting and request-error ports.
observability|published-language|Uses published safe logging and security-warning language.
""",
    ),
    units=units(
        """
@vo|base/types/auth.py|RegisterRequest LoginRequest AuthResponse
@vo|base/types/user.py|UserBase UserUpdate UserResponse UserAiSettingsUpdate UserAiSettingsResponse
@vo|base/types/ai_feedback.py|AiFeedbackRequest AiFeedbackResponse
User|agg
AiFeedback|ent
@svc|extension/security.py|create_access_token decode_access_token hash_password verify_password
get_current_user_id|svc|extension/auth.py
@svc|extension/api/auth.py|register login
bind_authenticated_user_context|svc|extension/observability.py
purge_test_accounts|svc|extension/account_purge.py
PurgeReport|vo
UserRepository|repo|base/repository.py|extension/sql.py
"""
    ),
    interface="""
AUTH_COOKIE_NAME AiFeedback AiFeedbackRequest AiFeedbackResponse
AiSuggestionListResponse AiSuggestionResponse AuthResponse
DEFAULT_TEST_EMAIL_PATTERN LoginRequest PurgeReport RegisterRequest User
UserAiSettingsResponse UserAiSettingsUpdate UserBase UserRepository UserResponse
UserUpdate auth_rate_limiter auth_router bind_authenticated_user_context
create_access_token decode_access_token get_current_user_id get_me hash_password
is_safe_purge_environment login normalize_email oauth2_scheme purge_test_accounts
register register_in_flight_parse_checker register_rate_limiter users_router
verify_password
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_identity_package.py
converges-by-layer|The package converges into base/ (pure core) + extension/ (edges).|test_identity_converges_by_layer
single-home-no-residue|The pre-migration god-files are deleted — identity is the single home.|test_identity_god_files_are_gone
repository-split|The UserRepository port splits into a base port + an extension SQL adapter.|test_identity_repository_split
base-layer-pure|The base/ layer never imports the package's own extension/ layer.|test_identity_base_layer_is_pure
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_identity_interface_equals_published_language
passes-own-governance-gate|Check_package_contract validates identity with no violations.|test_identity_package_contract_gate_passes
"""
    ),
    roadmap=acs(
        "identity",
        """
@$be/identity/test_auth_router.py|P0
1.1|Email identity is unique case-insensitively.|test_register_duplicate_email
1.2|Case-variant email is normalized on registration and login.|test_AC1_10_2_register_rejects_case_variant_duplicate_email
2.1|Registration accepts a valid payload, bcrypt-hashes the password.|test_register_success
2.2|Login accepts valid credentials and returns a JWT + HttpOnly cookie.|test_login_success
2.3|Registration handles the duplicate-email IntegrityError race with a clean 400.|test_register_integrity_error_race_condition|P1
2.5|The auth dependency accepts the HttpOnly session cookie directly for GET /auth/me.|test_AC1_10_3_get_me_accepts_httponly_cookie|P1
2.6|Browser logout expires the HttpOnly authentication cookie at its original scope, is idempotent.|test_browser_logout_expires_cookie
2674.1|Uq_users_email_normalized is a partial unique index scoped to is_deleted = false.|test_AC_identity_2674_1_soft_deleted_user_email_can_reregister|P1
2674.2|Global and auth rate limiters extract the client IP.|test_AC_identity_2674_2_get_client_ip_uses_rightmost_forwarded_ip_and_shares_helper|P1
@$be/identity/test_auth_shift_left.py|P0
journeys.1|A new user can register and log in end to end.|test_password_hashing_and_verification
journeys.2|API authentication failures return a clean 401/422, not a 500.|test_invalid_token_rejected_with_401
journeys.3|Unauthenticated requests to protected endpoints are blocked with 401.|test_unauthenticated_request_blocked
journeys.4|A user's session is created, reused.|test_jwt_session_token_lifecycle|P1
@$e2e/test_auth_flows.py|P1
journeys.5|The frontend registration E2E targets the mode-toggle register control by test id and switches into register mode.|test_full_registration_flow
journeys.6|On an explicitly pinned deployment a new browser user registers, survives reload, logs out.|test_browser_cookie_logout_lifecycle|P0
@$be/identity/test_account_purge.py|P1
purge.1|Only disposable test accounts are selected for purging.|test_selection_matches_test_accounts_and_excludes_real_ones
purge.2|Applying the purge removes a clean test account and every row it owns.|test_apply_purges_clean_account_and_leaves_others
purge.3|An account owning a posted ledger entry is reported blocked and fully preserved, never force-deleted.|test_account_with_posted_ledger_entry_is_blocked_not_deleted
purge.4|A dry run names the accounts it would purge but persists no deletions.|test_dry_run_reports_but_persists_nothing
purge.5|The CLI --apply environment guard allows dev/staging/CI and refuses production.|test_environment_guard_allows_dev_staging_and_refuses_production
@$fe/__tests__/auth.test.ts|P2
fe-auth.1|`getUserId` returns `null` when not set.|AC16.5.1/AC16.5.2 returns null when key is not set
fe-auth.2|`getUserId` returns stored `userId` from `localStorage`.|AC16.5.2 returns stored userId from localStorage
fe-auth.3|`setUser` stores `userId` and `email` in `localStorage` and nothing else.|AC16.5.3 stores userId and email
fe-auth.4|`clearUser` removes all auth keys from `localStorage`.|AC16.5.4 removes all auth keys from localStorage
fe-auth.5|`isAuthenticated` returns `true`.|AC16.5.5 returns true when non-secret user session metadata exists
@$fe/__tests__/loginPage.test.tsx|P1
fe-auth.6|Login page submits login payload and redirects on success.|AC16.12.5 AC22.1.3 submits login payload and redirects to Home|P2
fe-auth.7|Login page toggles register mode and switches endpoint for submit.|AC16.12.6 switches to register mode and uses register endpoint|P2
fe-auth.8|Login page shows API error messages and resets loading state on failure.|AC16.12.7 shows API error and exits loading state|P2
fe-auth.9|Toggles password visibility.|AC16.12.13 toggles password visibility
fe-auth.10|Shows error with alert role and aria-live.|AC16.12.14 shows error with alert role and aria-live
fe-auth.11|Shows mode toggle links.|AC16.12.15 shows mode toggle links
fe-auth.12|Shows loading spinner during submission.|AC16.12.16 shows loading spinner during submission
fe-auth2.2|Login auth controls expose distinct `data-testid` hooks and accessible names.|AC8.19.1 login register controls expose distinct test ids and accessible names
@$fe/__tests__/shellAndAuth.test.tsx|P2
fe-auth.13|App shell renders workspace providers and main content with collapse-aware layout.|AC16.19.1 renders providers and collapse-aware shell layout
fe-auth.14|Auth guard redirects unauthenticated protected routes and allows public routes.|AC16.19.2 redirects unauthenticated protected routes
@$fe/__tests__/appShellSessionBootstrap.test.tsx|P1
fe-ia-identity.1|A typed `fetchCurrentUser` client function consumes `GET /api/auth/me`.|AC22.15.3 does not call /auth/me when there is no local session
2478.1|UseSessionBootstrap clears local session storage only.|AC-identity.2478.1 keeps the local identity when /auth/me is aborted or the network fails
@-|P1
vocabulary-ownership.1|User CRUD and AI-settings request/response DTOs are identity-owned base value objects.|$t/test_vocabulary_ownership.py::test_AC_identity_vocabulary_ownership_1_identity_owns_user_dtos
2.4|A valid JWT bearer token grants 200 on a protected endpoint.|$be/identity/test_auth.py::test_auth_valid_user
fe-auth.15|Desktop and mobile logout wait for server cookie expiration.|$fe/__tests__/sidebarAndTabs.test.tsx::waits for cookie logout before clearing desktop identity|P0
1.3|The /users management endpoints expose authenticated current-user operations.|$be/identity/test_users_router.py::test_AC1_8_1_get_user_by_id_hides_other_users
fe-auth2.1|Frontend storage keeps only non-secret user metadata, relying on the HttpOnly session cookie.|$fe/__tests__/apiFunctions.test.ts::AC1.10.3 sends HttpOnly auth cookies by default|P2
ai-suggestions.1|`GET /ai/suggestions` enforces a bounded page size.|$be/api/test_ai_feedback_router.py::test_AC_ai_suggestions_1_list_rejects_unbounded_limit
""",
    ),
    concepts=concepts(
        """
identity_wire_vocabulary|common/identity/readme.md#wire-vocabulary-ownership|Identity-owned auth, user CRUD, AI settings, and feedback request/response value objects.|-|-|identity|concept
"""
    ),
)
