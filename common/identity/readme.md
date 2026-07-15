# `identity` — users, authentication & AI-feedback (domain package)

> The vertical **identity** bounded context: the `User` aggregate root, its
> `AiFeedback` child entity, and the authentication domain (register / login /
> resolve-current-user). Machine contract: [`contract.py`](./contract.py).
> Worklist: [`todo.md`](./todo.md).
>
> This `common/identity/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/identity`](../../apps/backend/src/identity)
> (`contract.implementations["be"]`). This readme **internalizes the auth SSOT**
> that previously lived at `docs/ssot/auth.md` (the backend half — the frontend /
> browser-security half moved to `apps/frontend/frontend-patterns.md`, its existing
> owner).

## Why

Every user-scoped request must resolve identity from a cryptographic token, and
new users must register / log in. `identity` is the package that owns that: a
mandatory JWT/OAuth2 identity system, the `User` aggregate it authenticates
against, and the `AiFeedback` entity capturing a user's verdict on an AI
suggestion.

## Ubiquitous language

- **User** — the *aggregate root* of this context: an authenticated account keyed
  by a normalized email. Its invariant is **email unique case-insensitively**,
  enforced by the `func.lower(email)` unique index `uq_users_email_normalized` — a
  duplicate in any case variant is unrepresentable at the DB level.
- **AiFeedback** — a child *entity* of `User` (FK to `users.id`, `ON DELETE
  CASCADE`): a user's accept/reject/edit verdict on an AI classification or
  reconciliation suggestion.
- **`normalize_email`** — the canonical identity key: trim + Unicode case-fold, so
  case/whitespace variants resolve to one identity. Applied on both registration
  and login lookup.
- **`AUTH_COOKIE_NAME`** (`finance_access_token`) — the HttpOnly browser
  session-cookie carrying the JWT.
- **`RegisterRequest` / `LoginRequest` / `AuthResponse`** — the published wire
  value objects of the auth boundary.

## Authentication model

**Mechanism**: JWT (HS256) authenticated from either an HttpOnly browser cookie or
a bearer token.

- **Token storage** — browser default: the HttpOnly cookie `finance_access_token`;
  API/test compatibility: `Authorization: Bearer <jwt>`. Token lifetime: 1 day
  (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`). The `sub` claim is the user id.
- **Backend validation** — `get_current_user_id` resolves the bearer token first,
  then the HttpOnly cookie; validates the JWT signature with `SECRET_KEY`; extracts
  the user id from `sub`; and verifies the user still exists (a user-existence
  check on every authenticated request, since there is no token-revocation list).
- **Behavior** — missing token → `401`; invalid/expired token → `401`; valid token
  whose user was deleted → `401`; valid token → the request proceeds with the
  resolved `user_id`.
- **Email identity** — registration and login normalize the email (trim + case
  fold) before lookup and persistence; the unique normalized-email index makes
  case variants unable to create duplicate accounts.

**Red line — no `X-User-Id` header**: identity is *only* ever derived from the
validated JWT subject. Direct use of an `X-User-Id` header for identity resolution
is strictly prohibited in every environment.

**Scope** — accounts, journal entries, statements, reports, reconciliation, and
chat endpoints are user-scoped via `get_current_user_id`. Reconciliation endpoints
**must** be authenticated and user-scoped — unauthenticated access to reconciliation
data is prohibited, including in MVP/test. The legacy `/users` routes are **not** a
public registration surface; public registration is owned by `/auth/register`, and
`/users` exposes only authenticated current-user compatibility operations.

## Registration & login API

### `POST /api/auth/register`

Creates a new user with email + password. Password is bcrypt-hashed (plaintext is
never stored); email uniqueness is enforced at the DB level; rate limited per IP.
Returns `201` with `{id, email, name, created_at, access_token}` + the HttpOnly
cookie.

### `POST /api/auth/login`

Authenticates email + password (constant-time bcrypt comparison; a generic error
that does not reveal whether the email exists). Rate limited per IP. Returns `200`
with the same shape as register + a fresh cookie.

### `GET /api/auth/me`

Returns the current authenticated user.

### Legacy `/users` compatibility API

Retained for compatibility only: `POST /users` requires auth and returns a
migration error pointing at `/auth/register`; `GET /users` returns only the
authenticated user's profile; `GET|PUT /users/{user_id}` are allowed only when
`user_id` matches the JWT subject (otherwise not-found, no cross-user leakage);
`DELETE /users/{user_id}` deletes the caller's own account (refusing while a
statement parse is in flight, or while posted/reconciled ledger entries exist).

## Internal layering (`base` / `extension`)

### Wire vocabulary ownership

Identity owns the auth, user CRUD, AI-settings, and feedback request/response
value objects in `base/types/`. `src.schemas.user` retains compatibility
re-exports and the generic `ListResponse[UserResponse]` wire envelope; identity
implementation code imports its owned base vocabulary directly.

| layer | what lives here |
|-------|-----------------|
| `base/types/` | the pure value objects: `RegisterRequest`/`LoginRequest`/`AuthResponse`, owned `User*` CRUD and AI-settings DTOs (the generic list envelope remains in `src.schemas.user`), the `AiFeedback*` request/response shapes, `normalize_email`, `AUTH_COOKIE_NAME` (no ORM, no transport) |
| `base/repository.py` | the `UserRepository` **port** (a `typing.Protocol`) the pure core depends on |
| `extension/sql.py` | the `User` aggregate + `AiFeedback` entity ORM models **and** `SqlUserRepository` (the only role that touches the ORM) — the port's adapter (mechanism B) |
| `extension/security.py` | `create_access_token`/`decode_access_token` (JWT) + `hash_password`/`verify_password` (bcrypt) domain services |
| `extension/auth.py` | `get_current_user_id` (the FastAPI auth dependency) + `oauth2_scheme` |
| `extension/rate_limit.py` | `auth_rate_limiter`/`register_rate_limiter` (auth-endpoint throttles, built from the `platform` `RateLimiter`) |
| `extension/observability.py` | `bind_authenticated_user_context` (structlog user binding) |
| `extension/account_purge.py` | `purge_test_accounts`/`is_safe_purge_environment`/`PurgeReport` — the test/QA account-purge maintenance service (folded in from `src/services`, #1677; operator CLI: `tools/purge_test_accounts.py`) |
| `extension/api/` | the `/auth` (`register`/`login`/`get_me`) + `/users` routers (the transport edge) |

**Dependency rule (DAG, down only)**: `extension → base`; the package depends
downward on `platform` (the rate limiter), `observability` (the security-warning
log), and `config` (settings, imported by its bare published root) — all
`infra`-class, declared in `contract.depends_on`. The ORM / `AsyncSession` lives
only in `extension` and never leaks into `base`.

`get_current_user_id` is the request chokepoint, reached by routers through
`src/deps.py`'s `CurrentUserId` alias (so most routers need no identity import).

## Public vs internal

**Public** (`__all__`, == `contract.interface`): the value objects, `User`,
`AiFeedback`, `UserRepository`, the security domain services, `get_current_user_id`
/ `oauth2_scheme`, `register` / `login` / `get_me`, the rate limiters,
`bind_authenticated_user_context`, and the `auth_router` / `users_router`.

**Internal** (not published): `SqlUserRepository` (reached only through the
`UserRepository` port) and module internals (`_check_rate_limit`, `_get_client_ip`,
`_set_auth_cookie`).

## Storage

`users(id, email, name, hashed_password, ai_settings, …)` with a unique
case-insensitive email index `uq_users_email_normalized`; `ai_feedback(id,
suggestion_id, user_id→users.id ON DELETE CASCADE, action, corrected_value, …)`.
The cutover is a pure code move — the table names, columns, and indexes are
unchanged from the pre-migration `src/models/user.py` (long since deleted; the
ORM now lives at `apps/backend/src/identity/extension/sql.py`), so no schema
migration is required.

## Security considerations

- **Password security** — bcrypt with automatic per-password salt; constant-time
  comparison.
- **JWT security** — HS256, secret in `SECRET_KEY` (the protected-runtime
  bootloader refuses to start with a development-default / empty / <32-byte
  secret). Signature + expiration verified on every request.
- **Rate limiting** — login: 5 attempts / minute / IP; registration: configurable
  (default 10 / 600s) / IP; trusted-proxy support via `TRUST_PROXY`; auto-reset on
  successful auth.
- **Token revocation** — no blacklist; tokens are valid until expiry, mitigated by
  the per-request user-existence check.

## Governance

The package's ACs (`AC-identity.user.*` / `AC-identity.auth.*`) live in
[`contract.py`](./contract.py)'s `roadmap` and are sourced **directly** from there
into the AC registry (no EPIC mirror — the rows were removed from EPIC-001 with a
disclaimer pointing here). Its invariants pin to the tests that prove them;
`tools/check_package_contract.py` validates the implementation against this
contract (interface == `__all__`, kind placement, the `UserRepository` port/adapter
split, no upward import edge, single-home/zero-residue).
