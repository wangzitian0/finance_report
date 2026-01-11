# Authentication SSOT

> **SSOT Key**: `authentication`
> **Core Definition**: How API requests resolve the current user identity.

---

## 1. Source of Truth

| Component | Physical Location | Description |
|-----------|-------------------|-------------|
| User context dependency | `apps/backend/src/auth.py` | `get_current_user_id` header-based resolver |
| API routers | `apps/backend/src/routers/` | User-scoped endpoints depend on `get_current_user_id` |
| User model | `apps/backend/src/models/user.py` | Persistence for valid user IDs |

---

## 2. Current Authentication Model (MVP)

**Mechanism**: Request header `X-User-Id` (UUID).

**Behavior**:
- Missing header -> `401 Unauthorized`
- Invalid/unknown user ID -> `401 Unauthorized`
- Valid user ID -> request proceeds

**Scope**:
- Accounts, journal entries, statements, reports, reconciliation, and chat endpoints.
- Reconciliation endpoints **must** be authenticated and user-scoped via `get_current_user_id`. Unauthenticated access to reconciliation data is **prohibited**, including in MVP and test environments.

---

## 3. Security Considerations

> **Warning**: The `X-User-Id` header is currently trusted without cryptographic verification. This allows any client to impersonate any user by sending a valid UUID.

### Risk Mitigation
- **Private Access Only**: This API must NOT be exposed to the public internet without a trusted upstream gateway (e.g., Kong, Nginx) that handles auth and sanitizes this header.
- **Production Requirement**: Before production release, this mechanism MUST be replaced by:
  1. **OIDC/JWT Tokens**: Validated by the backend.
  2. **Trusted Gateway**: Where the gateway authenticates the user and injects the `X-User-Id` header (stripping any client-provided value).

---

## 4. Design Constraints

### Required
- **No hard-coded user IDs** in routers or services.
- **User existence check** against `users` table before processing.
- **UUID validation** on the header value.

### Prohibited
- **Mock user bypass** in production code.
- **Implicit defaults** when the user header is missing.

---

## 5. Playbook

### Local Development
1. Create a user record in the database.
2. Send `X-User-Id` in all user-scoped API requests.

### Testing
- Tests must create a user and attach `X-User-Id` via client headers.

---

## 6. Verification (The Proof)

```bash
curl -H "X-User-Id: <uuid>" http://localhost:8000/api/accounts
# Expect 200 with data

curl http://localhost:8000/api/accounts
# Expect 401 Missing X-User-Id header
```
