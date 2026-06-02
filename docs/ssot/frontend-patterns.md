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

## 4. UI Primitives

Frontend application controls use a small React primitive layer in
`apps/frontend/src/components/ui/index.tsx`. New page code should prefer these
primitives over repeating page-local class recipes.

### Current primitives

- `Button` — primary, secondary, ghost, and danger actions.
- `IconButton` — icon-only actions with a required `label` that maps to
  `aria-label` and `title`.
- `Badge` — semantic status labels.
- `Alert` — error/success/warning/info messages with live-region semantics.
- `EmptyState` — reusable empty and retry surfaces.
- `LoadingState` — reusable loading state with `role="status"`.
- `PageHeader` — consistent page title, description, and action layout.

### Rules

- Use `IconButton` for icon-only actions. Do not rely on `title` alone for an
  accessible name.
- Use `Alert`, `EmptyState`, and `LoadingState` for repeated loading/error/empty
  surfaces before adding page-local markup.
- Use `framed={false}` for states rendered inside an existing card so the UI
  does not create nested cards.
- Preserve existing CSS variable usage. The primitive layer does not replace the
  design-token follow-up tracked by issue #613.
- Component tests must reference the owning AC IDs when primitives gain new
  behavior or variants.

### Applied In

- `app/(main)/accounts/page.tsx`
- `app/(main)/statements/page.tsx`
- `src/__tests__/uiPrimitives.test.tsx`
- `src/__tests__/accountsPage.test.tsx`
- `src/__tests__/statementsPage.test.tsx`

## 5. API Integration

All API calls must go through the centralized `apiFetch` or `apiUpload` utility in `lib/api.ts`.

**Rules:**
- **NO Direct `fetch()`**: Never use the native `fetch()` API for internal `/api/*` calls.
- **Authorization**: The utility automatically injects the `Bearer <token>` header from local storage.
- **Absolute URLs**: Use the `APP_URL` constant from `lib/api.ts` when you need to refer back to the frontend domain.

## 6. Monetary Amounts

Frontend monetary display and arithmetic must use `decimal.js` through `src/lib/currency.ts`.

**Rules:**
- Do not convert money with `Number()`, `parseFloat()`, or `toFixed()` in page/component code.
- Use `formatCurrencyLocale()` for currency display; it formats from Decimal/string values without JS number precision loss.
- Use `sumAmounts()`, `subtractAmounts()`, `compareAmounts()`, and `toDecimal()` for monetary calculations and comparisons.
- Chart geometry may use `amountToChartNumber()` because chart libraries require `number` coordinates; do not reuse chart numbers for accounting totals or displayed money.

## 7. Responsive Navigation

Desktop sidebar and mobile drawer navigation share `components/navigation.ts` as the route source of truth.

**Rules:**
- Add primary app routes once in `primaryNavItems`.
- Add workspace tab labels/icons once in `ROUTE_CONFIG`.
- Mobile must not render desktop workspace tabs; phone navigation uses the drawer only.
- Do not create separate reduced mobile menus that hide core routes.

## 8. Mobile Review Surfaces

Review and journal workflows must be usable at phone widths without relying on
document-level horizontal scrolling.

**Rules:**
- Key review routes and dialogs must keep `document.documentElement.scrollWidth`
  less than or equal to `clientWidth` at 375-390 px viewports.
- Account-management and review routes must keep `document.documentElement.scrollWidth`
  less than or equal to `clientWidth` at 375-390 px viewports.
- Desktop data tables may remain tables at `md` and wider breakpoints only when
  their local scroll containers do not hide required review information at
  1440 px with the sidebar visible.
- Phone layouts for action-heavy review queues should use stacked cards so
  primary actions and correction inputs are visible without horizontal dragging.
- Dense accounting details may keep desktop tables, but phone layouts must expose
  account, direction, amount, and currency as readable line cards.
- Phone account rows must stack account identity, metadata, balance, and row
  actions so long account names cannot overlap amounts or controls.
- Use Playwright for route-level mobile overflow checks and component tests for
  mobile card affordances.

**Applied In:**
- `app/(main)/accounts/page.tsx`
- `app/(main)/review/ai-suggestions/page.tsx`
- `app/(main)/statements/[id]/review/page.tsx`
- `components/review/Stage2ReviewQueue.tsx`
- `components/review/TransactionTable.tsx`
- `components/journal/JournalEntryDetailsModal.tsx`
- `playwright/mobile-ux.spec.ts`

## 9. App Metadata & PWA Head Tags

Root app metadata lives in `app/layout.tsx`.

**Rules:**
- Keep PWA manifest and icon metadata in the `metadata` export.
- Keep viewport-related fields, including `themeColor`, in the `viewport` export.
- Use `appleWebApp` for iOS web-app capability metadata; do not duplicate
  `apple-mobile-web-app-capable` in `metadata.other`.

## 10. Security & Authentication

- **AuthGuard**: Protects all `(main)` routes. Unauthorized users are redirected to `/login`.
- **Public Routes**: Only `/login` and `/ping-pong` are exempt from `AuthGuard`.
- **Injection Protection**: The `apiFetch` wrapper is the primary defense against missing user context.

## 11. Shared Types

To avoid duplication, shared interfaces are defined in `src/lib/types.ts`.

**Common Types:**
- `Account`
- `JournalEntry`, `JournalLine`
- `BankStatement`, `BankStatementTransaction`
- `ReportLine`, `BalanceSheetResponse`, `IncomeStatementResponse`
- `BrokerageImportResponse` — result of `POST /api/statements/{id}/brokerage/import`

**Usage:**
```typescript
import { Account, AccountListResponse } from "@/lib/types";

// components/accounts/AccountFormModal.tsx
```

## 12. Brokerage Import Completion Path

After a brokerage PDF is uploaded and parsed, users must be able to see the import status and navigate to their portfolio.

### Flow

```
Upload PDF → Parsing (polling) → parsed/approved status
  → "Import to Portfolio" button on statement detail page
  → POST /api/statements/{id}/brokerage/import
  → Success: show result banner (broker, positions, reconcile stats) + "View Portfolio →" link
  → Failure: show actionable error banner + "Retry Import" button
  → Portfolio page: Total Portfolio Value banner
```

### Rules

- The **"Import to Portfolio"** button is only visible when `statement.status === "parsed" || statement.status === "approved"` and no import result exists yet.
- On success, show a result banner with: broker name, positions parsed, new holdings created, holdings reconciled, and a link to `/portfolio`.
- On failure, show a safe error message. **Sensitive data (URLs, tokens, storage paths) must be stripped** before display. The `handleBrokerageImport` function applies a regex to replace `https://…` and `s3://…` with `[URL]`.
- The **Portfolio page** shows a "Total Portfolio Value" card when active holdings are present, computed as the sum of `market_value` across all active holdings.
- All API calls use `apiFetch` from `lib/api.ts` — never raw `fetch()`.

### Files

- `app/(main)/statements/[id]/page.tsx` — Import button, result/error banners
- `app/(main)/portfolio/page.tsx` — Total portfolio value banner
- `lib/types.ts` — `BrokerageImportResponse` interface
- `src/__tests__/statementDetailPage.coverage.test.tsx` — AC17.8.1–AC17.8.3, AC17.8.5
- `src/__tests__/portfolioPage.test.tsx` — AC17.8.4

## 13. Dashboard First-Run Onboarding

The Dashboard must give first-time users a direct path into the core flow instead of only rendering empty metrics.

### Code References

- `app/(main)/dashboard/page.tsx` — onboarding detection and links
- `src/__tests__/dashboardPage.test.tsx` — AC16.12.17–AC16.12.19 coverage
