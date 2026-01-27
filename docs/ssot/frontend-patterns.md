# Frontend Patterns (Source of Truth)

> **SSOT Key**: `frontend-patterns`
> **Purpose**: Architectural patterns and best practices for the Next.js frontend application.

---

## 1. Source of Truth

### Physical File Locations

| File | Purpose |
|------|---------|
| `apps/frontend/app/` | Next.js App Router pages |
| `apps/frontend/components/` | Reusable React components |
| `apps/frontend/lib/api.ts` | Centralized API client |
| `apps/frontend/lib/types.ts` | Shared TypeScript interfaces |
| `apps/frontend/lib/theme.ts` | Theme state management |
| `apps/frontend/app/globals.css` | CSS variables and global styles |
| `apps/frontend/components/auth/AuthGuard.tsx` | Route protection |

### Overview

All new feature development must adhere to these patterns. The frontend uses Next.js 14 with App Router, React Server Components by default, and TypeScript strict mode.

---

## 2. Architecture Model

### Server-Side Rendering (SSR) vs. Client-Side Rendering (CSR)

#### Mounted State Pattern

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

### Theme System

We use CSS variables for theming to avoid flash of unstyled content (FOUC) and support system preferences.

**Structure:**
- `app/globals.css`: Defines `:root` (light) and `.dark` variables.
- `lib/theme.ts`: Manages theme state validation and persistence.
- `ThemeToggle.tsx`: Semantic button for switching themes.

### API Integration

All API calls must go through the centralized `apiFetch` or `apiUpload` utility in `lib/api.ts`.

**Key Features:**
- **X-User-Id**: Automatically injects the `X-User-Id` header from local storage.
- **Absolute URLs**: Use the `APP_URL` constant when you need to refer back to the frontend domain.
- **Error Handling**: Standardized error responses.

### Security & Authentication

- **AuthGuard**: Protects all `(main)` routes. Unauthorized users are redirected to `/login`.
- **Public Routes**: Only `/login` and `/ping-pong` are exempt from `AuthGuard`.
- **Injection Protection**: The `apiFetch` wrapper is the primary defense against missing user context.

### Shared Types

To avoid duplication, shared interfaces are defined in `src/lib/types.ts`.

**Common Types:**
- `Account`
- `JournalEntry`, `JournalLine`
- `BankStatement`, `BankStatementTransaction`
- `ReportLine`, `BalanceSheetResponse`, `IncomeStatementResponse`

---

## 3. Design Constraints

### Hard Rules

| Rule | Description |
|------|-------------|
| **No Direct `fetch()`** | Never use the native `fetch()` API for internal `/api/*` calls — use `lib/api.ts` |
| **No `any` Types** | TypeScript strict mode — no `any` types allowed |
| **CSS Variables Required** | Use CSS variables for colors, not hardcoded hex or Tailwind defaults |
| **Server Components Default** | Use Server Components by default; add `'use client'` only when necessary |
| **AuthGuard Required** | All `(main)` routes must be protected by AuthGuard |

### CSS Variable Usage

```css
/* Good */
bg-[var(--background-card)]
text-[var(--muted-foreground)]

/* Avoid */
bg-white
text-gray-500
```

### Import Patterns

```typescript
// Good - Use shared types
import { Account, AccountListResponse } from "@/lib/types";

// Good - Use centralized API
import { apiFetch } from "@/lib/api";

// Bad - Direct fetch
fetch("/api/accounts");  // ❌ Missing X-User-Id header
```

---

## 4. Playbooks (SOP)

### Adding a New Page

1. Create page in `apps/frontend/app/(main)/[route]/page.tsx`
2. Use Server Component by default
3. Add to navigation if needed
4. AuthGuard protects automatically (under `(main)` group)

```tsx
// apps/frontend/app/(main)/my-feature/page.tsx
export default function MyFeaturePage() {
  return (
    <div>
      <h1>My Feature</h1>
    </div>
  );
}
```

### Adding a Client Component

1. Add `'use client'` directive at top
2. Handle hydration with mounted state if using localStorage/window
3. Use `apiFetch` for API calls

```tsx
'use client';

import { useState, useEffect } from 'react';
import { apiFetch } from '@/lib/api';

export function MyClientComponent() {
  const [mounted, setMounted] = useState(false);
  const [data, setData] = useState(null);

  useEffect(() => {
    setMounted(true);
    apiFetch('/api/my-endpoint').then(setData);
  }, []);

  if (!mounted) return <Skeleton />;
  return <div>{/* render data */}</div>;
}
```

### Adding a New API Type

1. Define interface in `lib/types.ts`
2. Export from types file
3. Import in components that need it

```typescript
// lib/types.ts
export interface MyNewEntity {
  id: string;
  name: string;
  createdAt: string;
}

export interface MyNewEntityListResponse {
  items: MyNewEntity[];
  total: number;
}
```

### Theme Customization

1. Add CSS variables to `globals.css`
2. Define both light (`:root`) and dark (`.dark`) values
3. Use `var(--variable-name)` in components

```css
/* app/globals.css */
:root {
  --my-custom-color: #123456;
}

.dark {
  --my-custom-color: #654321;
}
```

---

## 5. Verification (The Proof)

### TypeScript Check

```bash
# Run type check
moon run frontend:typecheck

# Or directly
cd apps/frontend && npx tsc --noEmit
```

### Lint Check

```bash
# Run ESLint
moon run frontend:lint
```

### Build Verification

```bash
# Build frontend
moon run frontend:build

# Expected: No errors, successful build
```

### Local Development

```bash
# Start frontend dev server
moon run frontend:dev

# Open http://localhost:3000
```

### Hydration Error Check

After adding client components:
1. Open the page in browser
2. Check console for hydration warnings
3. If present, add mounted state pattern

### API Integration Check

```bash
# Verify API calls include X-User-Id header
# Open browser DevTools → Network tab
# Make an API call
# Check request headers for X-User-Id
```

---

*Last updated: 2026-01-27*
