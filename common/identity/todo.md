# `identity` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] Cut over `identity` to the `base`/`extension` building-block layering
      (#1428): the `User` aggregate + `AiFeedback` entity, the auth value objects,
      the `UserRepository` port + SQL adapter, the JWT/bcrypt security services,
      `get_current_user_id`, `register`/`login`, the auth rate limiters,
      observability binding, and the `/auth` + `/users` routers.
- [x] Single home, zero residue: the pre-migration god-files (`src/auth.py`,
      `src/security.py`, `src/rate_limit.py`, `src/observability_events.py`,
      `src/routers/auth.py`, `src/routers/users.py`, `src/schemas/auth.py`,
      `src/schemas/ai_feedback.py`, `src/models/user.py`) are deleted; consumers
      repointed to the published interface.
- [x] ACs (`AC-identity.user.*` / `AC-identity.auth.*`) sourced directly from the
      contract `roadmap`; removed from the EPIC-001 table with a disclaimer.
- [x] Internalized the auth SSOT: the backend half moved into
      [`readme.md`](./readme.md); the frontend/browser-security half moved to
      `apps/frontend/frontend-patterns.md`; `docs/ssot/auth.md` deleted and the
      `auth_flow` MANIFEST concept retired.

## Next

- [ ] Introduce `UserRegistered` / `UserLoggedIn` / `PasswordChanged` domain
      events on the `platform` outbox so other contexts can react without
      importing identity internals (`events=[]` today).
- [ ] Add a frontend implementation (`apps/frontend/src/lib/identity`) and set
      `implementations["fe"]` for the conforming auth client.
- [ ] Add a password-change / token-revocation path if a use case needs it
      (today tokens are valid until expiry, mitigated by the per-request
      user-existence check).
