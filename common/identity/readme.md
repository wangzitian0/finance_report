# `identity` — Users, Authentication & AI Feedback

Owns the `User` aggregate (`uq_users_email_normalized` via `normalize_email`), `AiFeedback`, and JWT authentication (`apps/backend/src/identity/`).

## Authentication & Security Model

- **Tokens**: HS256 JWT (`SECRET_KEY`), read from `Authorization: Bearer <jwt>` or the `finance_access_token` HttpOnly cookie (`POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` 204). Never trust `X-User-Id` headers.
- **Passwords & throttling**: Bcrypt salted hashes; constant-time verification; IP rate limiting via `platform` (`auth_rate_limiter`, `register_rate_limiter`). Protected runtimes fail closed in `boot.py` on weak `SECRET_KEY`.

### Wire vocabulary ownership

`base/types/` exports pure auth, user, AI-settings, and `AiFeedback*` DTOs (`__all__ == contract.interface`); `base/repository.py` defines the `UserRepository` protocol; `extension/sql.py` implements `SqlUserRepository` and ORM models; `extension/account_purge.py` handles test-account cleanup (`tools/` / `common/runtime/dev/`).
