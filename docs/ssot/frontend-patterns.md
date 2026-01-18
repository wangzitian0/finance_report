# Frontend Patterns & Architecture

## 1. Single Source of Truth
This document defines the architectural patterns and best practices for the frontend application. All new feature development must adhere to these patterns.

## 2. Server-Side Rendering (SSR) vs. Client-Side Rendering (CSR)

### Mounted State Pattern
Since we use client-side state (like `useWorkspace`) that relies on `localStorage` or `window`, we must handle hydration mismatches.

**Problem:**
Rendering component state directly from storage causes server/client mismatch errors.

**Solution:**
Use a custom `useMounted` hook or local state to ensure client-only rendering for specific parts.

```tsx
// Pattern
const [mounted, setMounted] = useState(false);
useEffect(() => setMounted(true), []);

if (!mounted) return null; // or loading skeleton
```

**Applied In:**
- `ThemeToggle.tsx`
- `Sidebar.tsx` (for collapse state)

## 3. Theme System

We use CSS variables for theming to avoid flash of unstyled content (FOUC) and support system preferences.

**Structure:**
- `app/globals.css`: Defines `:root` (light) and `.dark` variables.
- `lib/theme.ts`: Manages theme state validation and persistence.
- `ThemeToggle.tsx`: Semantic button for switching themes.

**Usage:**
Always use CSS variables instead of hardcoded hex values or Tailwind utilities that don't map to variables.
```css
/* Good */
bg-[var(--background-card)]
text-[var(--muted-foreground)]

/* Avoid */
bg-white
text-gray-500
```

## 4. API Integration

All API calls must go through the centralized `apiFetch` or `apiUpload` utility in `lib/api.ts`.

**Rules:**
- **NO Direct `fetch()`**: Never use the native `fetch()` API for internal `/api/*` calls.
- **X-User-Id**: The utility automatically injects the `X-User-Id` header from local storage.
- **Absolute URLs**: Use the `APP_URL` constant from `lib/api.ts` when you need to refer back to the frontend domain.

## 5. Security & Authentication

- **AuthGuard**: Protects all `(main)` routes. Unauthorized users are redirected to `/login`.
- **Public Routes**: Only `/login` and `/ping-pong` are exempt from `AuthGuard`.
- **Injection Protection**: The `apiFetch` wrapper is the primary defense against missing user context.

## 6. Shared Types

To avoid duplication, shared interfaces are defined in `src/lib/types.ts`.

**Common Types:**
- `Account`
- `JournalEntry`, `JournalLine`
- `BankStatement`, `BankStatementTransaction`
- `ReportLine`, `BalanceSheetResponse`, `IncomeStatementResponse`

**Usage:**
```typescript
import { Account, AccountListResponse } from "@/lib/types";

// components/accounts/AccountFormModal.tsx
```
