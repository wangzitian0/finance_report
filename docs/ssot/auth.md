# Auth SSOT (MIDDLEWARE ONE)

> **SSOT Key**: `auth`
> **Priority**: 0 (Critical Foundation)
> **Core Definition**: Mandatory JWT/OAuth2 identity system. All user-scoped requests must resolve identity via cryptographic tokens.

---

## 1. Source of Truth

| Component | Physical Location | Description |
|-----------|-------------------|-------------|
| User context dependency | `apps/backend/src/auth.py` | `get_current_user_id` JWT resolver for bearer and HttpOnly cookie credentials |
| Global security gate | `apps/backend/src/main.py` | CORS and security middleware configuration |
| User registration API | `apps/backend/src/routers/auth.py` | Registration and login endpoints |
| Legacy user profile API | `apps/backend/src/routers/users.py` | Authenticated current-user compatibility routes only |
| User model | `apps/backend/src/models/user.py` | Persistence for valid user IDs |
| Frontend auth context | `apps/frontend/src/lib/auth.ts` | User session management |
| API fetch with auth | `apps/frontend/src/lib/api.ts` | Same-origin cookie credentials and legacy bearer compatibility |
| Frontend security headers | `apps/frontend/next.config.mjs` | CSP and browser security response headers |

---

## 2. Authentication Flow

```mermaid
sequenceDiagram
    participant Browser
    participant Frontend
    participant Backend
    participant DB

    Note over Browser,DB: Registration Flow
    Browser->>Frontend: Fill registration form
    Frontend->>Backend: POST /api/auth/register {email, password}
    Backend->>Backend: Hash password with bcrypt
    Backend->>DB: Create user record
    DB-->>Backend: User ID (UUID)
    Backend->>Backend: Generate JWT token (sub: user_id)
    Backend-->>Frontend: {user_id, email, access_token} + HttpOnly cookie
    Frontend->>Browser: Store non-secret user metadata

    Note over Browser,DB: Login Flow
    Browser->>Frontend: Fill login form
    Frontend->>Backend: POST /api/auth/login {email, password}
    Backend->>DB: Query user by normalized email
    DB-->>Backend: User record
    Backend->>Backend: Verify password with bcrypt
    Backend->>Backend: Generate JWT token (sub: user_id)
    Backend-->>Frontend: {user_id, email, access_token} + HttpOnly cookie
    Frontend->>Browser: Store non-secret user metadata

    Note over Browser,DB: Authenticated Requests
    Browser->>Frontend: Navigate to /accounts
    Frontend->>Frontend: Check non-secret user metadata
    Frontend->>Backend: GET /api/accounts (HttpOnly cookie)
    Backend->>Backend: Decode & validate JWT
    Backend->>DB: Verify user exists
    Backend->>DB: Query user-scoped data
    DB-->>Backend: Data
    Backend-->>Frontend: 200 OK with data
    
    Note over Browser,DB: Unauthenticated Access
    Browser->>Frontend: Navigate to /statements (no token)
    Frontend->>Backend: GET /api/statements (no Authorization header)
    Backend-->>Frontend: 401 Unauthorized
    Frontend->>Browser: Redirect to /login
```

---

## 3. Current Authentication Model

**Mechanism**: JWT (JSON Web Token) authenticated from either an HttpOnly browser cookie or a bearer token.

**Token Storage**:
- Browser default: HttpOnly cookie (name: `finance_access_token`)
- API/test compatibility: `Authorization: Bearer <jwt_token>`
- Frontend storage: non-secret session metadata only (`finance_user_id`, `finance_user_email`)
- Token lifetime: 1 day (1440 minutes, configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)

**Backend Validation**:
- Resolves bearer tokens first, then the HttpOnly cookie
- Validates JWT signature with `SECRET_KEY`
- Extracts user ID from token payload (`sub` claim)
- Verifies user exists in database

**Behavior**:
- Missing cookie and bearer token → `401 Unauthorized`
- Invalid/expired cookie or bearer token → `401 Unauthorized`
- Valid token but user deleted → `401 Unauthorized`
- Valid token → request proceeds with resolved user_id

**Email Identity**:
- Registration and login normalize email addresses with trim + Unicode case folding before lookup and persistence.
- The database enforces a unique normalized-email index so case variants cannot create duplicate accounts.

**Prohibition (Red Line)**:
- **X-User-Id Header**: Direct use of `X-User-Id` for identity resolution is **STRICTLY PROHIBITED** in production and development. All identity must be derived from the validated JWT subject (`sub`).

**Scope**:
- Accounts, journal entries, statements, reports, reconciliation, and chat endpoints.
- Reconciliation endpoints **must** be authenticated and user-scoped via `get_current_user_id`. Unauthenticated access to reconciliation data is **prohibited**, including in MVP and test environments.
- Legacy `/users` routes are not a public registration surface. Public registration is owned by `/auth/register`; `/users` may only expose authenticated current-user compatibility operations.

---

### 3. Route Protection (Client-Side)

We use a global `AuthGuard` component in `layout.tsx` to protect routes.

**`components/AuthGuard.tsx`**
```tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/ping-pong"];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    if (PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(path + "/"))) {
      setAuthorized(true);
      return;
    }

    if (!isAuthenticated()) {
      setAuthorized(false);
      router.push("/login");
    } else {
      setAuthorized(true);
    }
  }, [pathname, router]);

  if (!authorized && !PUBLIC_PATHS.includes(pathname)) return null;

  return <>{children}</>;
}
```

**Usage in `layout.tsx`**
```tsx
export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        <AuthGuard>
           <AppShell>{children}</AppShell>
        </AuthGuard>
      </body>
    </html>
  );
}
```

---

## 4. Registration & Login API

### POST /api/auth/register

Creates a new user with email and password.

**Request**:
```json
{
  "email": "user@example.com",
  "name": "John Doe",
  "password": "secure_password_123"
}
```

**Response** (201 Created):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "John Doe",
  "created_at": "2026-01-22T00:00:00Z",
  "access_token": "<jwt-token-example>"
}
```

**Security Features**:
- Password hashed with bcrypt
- Rate limiting: 3 attempts per hour per IP
- Email uniqueness enforced at DB level

### POST /api/auth/login

Authenticates user with email and password.

**Request**:
```json
{
  "email": "user@example.com",
  "password": "secure_password_123"
}
```

**Response** (200 OK):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "John Doe",
  "created_at": "2026-01-22T00:00:00Z",
  "access_token": "<jwt-token-example>"
}
```

**Error Response** (401 Unauthorized):
```json
{
  "detail": "Invalid email or password"
}
```

**Security Features**:
- Constant-time password comparison
- Rate limiting: 5 attempts per 15 minutes per IP
- Generic error message (doesn't reveal if email exists)

### Legacy `/users` Compatibility API

The `/users` router is retained for compatibility only:

- `POST /users` requires authentication and returns a migration error directing clients to `/auth/register`.
- `GET /users` returns only the authenticated user's profile.
- `GET /users/{user_id}` and `PUT /users/{user_id}` are allowed only when `user_id` matches the JWT subject; other user IDs return not found.
- Unauthenticated access to any `/users` route returns `401 Unauthorized`.

### GET /api/auth/me

Returns current authenticated user information.

**Headers**:
```
Authorization: Bearer <access_token>
```

**Response** (200 OK):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "John Doe",
  "created_at": "2026-01-22T00:00:00Z",
  "access_token": "<jwt-token-example>"
}
```

---

## 5. Frontend Integration

### Session Storage

```typescript
// apps/frontend/src/lib/auth.ts
const USER_KEY = "finance_user_id";
const USER_EMAIL_KEY = "finance_user_email";
const TOKEN_KEY = "finance_access_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  // Legacy compatibility only. Browser auth uses the HttpOnly cookie.
  return localStorage.getItem(TOKEN_KEY);
}

export function setUser(userId: string, email: string, token: string): void {
  localStorage.setItem(USER_KEY, userId);
  localStorage.setItem(USER_EMAIL_KEY, email);
  localStorage.removeItem(TOKEN_KEY);
}

export function clearUser(): void {
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(USER_EMAIL_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getUserId() !== null;
}
```

### API Header Injection

```typescript
// apps/frontend/src/lib/api.ts
export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options?.headers,
  };
  
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  
  // Redirect to login on 401 Unauthorized
  if (!res.ok && res.status === 401) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  
  // ... handle other responses
}
```

### Auth Protection

Pages that require authentication should redirect to `/login` if `isAuthenticated()` returns false. The `AuthGuard` component in `layout.tsx` handles this globally for all protected routes.

---

## 6. Security Considerations

### JWT Token Security

**Current Implementation**:
- **Algorithm**: HS256 (HMAC with SHA-256)
- **Secret Key**: Stored in `SECRET_KEY` environment variable
- **Token Lifetime**: 1 day (1440 minutes, configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- **Token Claims**: `sub` (user ID), `exp` (expiration timestamp)

### Security Features

**Password Security**:
- Bcrypt hashing with automatic salt generation
- Cost factor: 12 (default bcrypt rounds)
- Constant-time comparison to prevent timing attacks

**Rate Limiting**:
- **Registration**: 3 attempts per hour per IP
- **Login**: 5 attempts per 15 minutes per IP
- Trusted proxy support via `TRUST_PROXY` environment variable
- Automatic reset on successful authentication

**Token Validation**:
- Signature verification on every request
- Expiration check (tokens auto-expire after 1 day)
- User existence verification against database
- Missing/invalid token → immediate 401 response

### Known Limitations

**Session Cookie**:
- Browser credentials are stored in an HttpOnly cookie and sent with same-origin API calls.
- Strict Content Security Policy (CSP) is still required to reduce XSS impact.
- Bearer tokens remain accepted for API clients and legacy tests, but frontend storage must not persist them.

**Token Revocation**:
- No blacklist mechanism (tokens valid until expiration)
- User account deletion does NOT immediately invalidate tokens
- **Workaround**: Database user existence check on every request

**Frontend Redirect**:
- Client-side 401 handling redirects to `/login`
- Requires JavaScript enabled
- **Limitation**: Direct API access (curl) still returns JSON error

### Production Requirements

Before production deployment, ensure:

1. **SECRET_KEY** is cryptographically random (min 32 bytes)
2. **HTTPS only** - Never expose session cookies or bearer tokens over HTTP outside local development
3. **CSP headers** - Reduce XSS risk and forbid `unsafe-eval`
4. **Rate limiting** - Configure appropriate limits for production traffic
5. **Token lifetime** - Consider shorter expiration for sensitive operations
6. **Monitoring** - Track failed auth attempts for security analysis

The backend bootloader enforces the first requirement for protected runtimes by
refusing to start with a development default secret, an empty secret, a secret
shorter than 32 bytes, a local development database URL, or the default local S3
secret. Staging, production, unknown environment names, and public HTTPS app
URLs are protected runtimes.

The frontend must emit security headers, including a Content Security Policy
with `frame-ancestors 'none'`. Browser session credentials must be sent through
the HttpOnly cookie; frontend storage must not persist bearer tokens.

---

## 7. Design Constraints

### Required
- **No hard-coded user IDs** in routers or services.
- **User existence check** against `users` table on every authenticated request.
- **JWT signature validation** on every request.
- **Frontend must include same-origin credentials** on authenticated API calls.
- **Token expiration check** - reject expired tokens immediately.

### Prohibited
- **Mock user bypass** in production code.
- **Implicit defaults** when authentication fails.
- **Storing passwords or bearer tokens** in frontend storage.
- **Trusting client-provided user IDs** without JWT validation.

---

## 8. Playbook

### Local Development
1. Start backend and frontend servers:
   ```bash
   moon run :dev -- --backend  # Terminal 1
   moon run :dev -- --frontend # Terminal 2
   ```
2. Navigate to `http://localhost:3000/login` or `/register`
3. Register a new user with email and password
4. The backend sets an HttpOnly auth cookie; frontend storage keeps only user id/email metadata

### Testing
- Browser tests must create a user via `/api/auth/register`, keep the auth cookie in the browser context, and avoid localStorage bearer tokens.
- Browser tests that issue direct API calls from Playwright must reuse the browser context cookie jar or send the `finance_access_token` cookie explicitly; they must not read bearer tokens from localStorage.
- Backend and API-client tests may include `Authorization: Bearer <token>` headers for direct request coverage.
- Example test setup:
  ```python
  # Backend test (pytest)
  response = client.post("/auth/register", json={
      "email": "test@example.com",
      "password": "secure123",
      "name": "Test User"
  })
  token = response.json()["access_token"]
  
  # Direct API clients may use bearer compatibility in subsequent requests.
  client.get("/accounts", headers={"Authorization": f"Bearer {token}"})
  ```

### Debugging "Not authenticated" / 401 Errors

**Frontend debugging**:
1. Open browser DevTools → Application → Local Storage
2. Check for `finance_user_id` and `finance_user_email` keys
3. If missing, navigate to `/login` and register/login
4. Verify API requests include the `finance_access_token` cookie
5. For API clients using bearer tokens, check token expiration by decoding the JWT payload

**Backend debugging**:
1. Check backend logs for JWT validation errors
2. Verify `SECRET_KEY` is set correctly in environment
3. Verify token signature matches the secret key
4. Check if user still exists in database

**Common issues**:
- **Token expired**: Re-login to get new token (7-day lifetime)
- **User deleted**: Token remains valid until expiration, but user check fails
- **Wrong SECRET_KEY**: Tokens generated with different key won't validate
- **Missing cookie**: Browser request context does not include `finance_access_token`

---

## 9. Verification (The Proof)

```bash
# 1. Register a new user
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "name": "Test User",
    "password": "secure_password_123"
  }'

# Expected response (201 Created):
# {
#   "id": "550e8400-e29b-41d4-a716-446655440000",
#   "email": "test@example.com",
#   "name": "Test User",
#   "created_at": "2026-01-22T00:00:00Z",
#   "access_token": "<jwt-token-example>"
# }

# 2. Login with existing user
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "secure_password_123"
  }'

# Expected response (200 OK):
# Same structure as registration response with new access_token

# 3. Use the token for authenticated requests
TOKEN="<jwt-token-example>"

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/accounts

# Expected: 200 OK with account data

# 4. Test without token (should fail)
curl -v http://localhost:8000/api/accounts

# Expected: 401 Unauthorized
# {"detail":"Not authenticated"}

# 5. Test with invalid token
curl -v -H "Authorization: Bearer invalid_token_here" \
  http://localhost:8000/api/accounts

# Expected: 401 Unauthorized
# {"detail":"Could not validate credentials"}

# 6. Get current user info
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/auth/me

# Expected: 200 OK
# {
#   "id": "550e8400-e29b-41d4-a716-446655440000",
#   "email": "test@example.com",
#   "name": "Test User",
#   "created_at": "2026-01-22T00:00:00Z",
#   "access_token": "<jwt-token-example>"
# }

# 7. Test frontend redirect on 401 (after PR #122 merges)
# Visit in browser (not logged in): http://localhost:3000/statements
# Expected: Automatically redirects to /login
```
