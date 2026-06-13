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
```text
/* Good */
bg-surface-card
text-content-muted

/* Avoid */
bg-white
text-gray-500
```

## 4. Design Tokens

The frontend token contract is defined in two layers:

- `apps/frontend/src/app/globals.css` owns the CSS variables for light and dark
  themes.
- `apps/frontend/tailwind.config.ts` maps those variables into Tailwind token
  names so components can use semantic classes instead of hardcoded palette
  utilities.

### Token Families

- **Surface and content colors**: `surface`, `surface-card`, `surface-muted`,
  `content`, `content-muted`, and `content-inverse`.
- **Border colors**: `border` and `border-hover`. Use `border-border` for
  standard outlines and dividers instead of arbitrary `border-[var(--border)]`
  recipes.
- **Action colors**: `accent`, `accent-hover`, and `accent-muted`.
- **Status colors**: `status-success`, `status-warning`, `status-error`, and
  `status-info`, each with a muted background token.
- **Chart colors**: `chart-1` through `chart-5`, plus `chart-trend-start` and
  `chart-trend-end`.
- **Typography**: `text-caption`, `text-body`, and `text-title` are the
  application scale for dense operational surfaces.
- **Spacing**: `page`, `panel`, and `control` tokens define recurring layout
  rhythm.
- **Radius**: `rounded-control`, `rounded-panel`, and `rounded-pill` are the
  supported control, card/panel, and pill shapes.
- **Elevation**: `shadow-card`, `shadow-floating`, and `shadow-focus`.
- **Layers**: `z-drawer`, `z-overlay`, `z-modal`, and `z-toast`.
- **Motion**: `duration-fast`, `duration-standard`, `duration-slow`,
  `ease-standard`, and `ease-emphasized`.

### Rules

- Prefer Tailwind token classes such as `bg-surface-card`, `text-content-muted`,
  `border-border`, `bg-status-success-muted`, and `rounded-control` over fixed
  palette classes such as `bg-green-100`, `text-gray-700`, or `rounded-xl`.
- Use semantic primitives (`Badge`, `Alert`, `Button`, `IconButton`) before
  adding one-off status recipes in pages.
- Status and confidence UI must use `badge-*`, `alert-*`, or another
  token-backed primitive class so light and dark themes share the same contract.
- New chart components must consume the `chart-*` palette instead of choosing
  local hues.
- New overlay/modal/sheet surfaces should use the layer tokens rather than local
  z-index numbers.

### Page-Local Visual Decisions

- Login uses the accent gradient for the primary submit action because it is the
  only public entry surface and intentionally has a stronger brand cue than the
  authenticated application shell. The gradient endpoints still come from
  `--accent` and `--accent-hover`.
- Dashboard cards and chart panels use the shared `card` class, tokenized
  radius, and `shadow-card`. Metric labels may keep uppercase caption treatment
  for scanability, but color, elevation, and radius must remain token-backed.
- Modal and sheet backdrops may use the shared overlay token because they need
  predictable contrast across light and dark themes.
- Any future page-local gradient, shadow, or radius choice must be documented in
  this section or replaced with an existing token.

### Applied In

- `tailwind.config.ts`
- `app/globals.css`
- `components/ui/ConfidenceBadge.tsx`
- `src/__tests__/designTokens.test.tsx`

## 5. UI Primitives

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
- Preserve the design-token contract. Primitive variants should map to token
  classes rather than hardcoded palette utilities.
- Component tests must reference the owning AC IDs when primitives gain new
  behavior or variants.
- Icon-only primitives own their accessible names. Callers must pass the
  required semantic label and must not override it through passthrough props.

### Accessibility and Visual Verification

Every UI-system change must leave both semantic and visual proof in the same PR.

### Global Accessibility Baseline

- `apps/frontend/src/app/globals.css` owns the app-wide keyboard and motion
  baseline. It must include `prefers-reduced-motion: reduce` handling that
  disables non-essential animation/transition timing and smooth scrolling.
- Global `:focus-visible` styling must cover links, buttons, form controls,
  summaries, focusable `[tabindex]` elements, and the shared `.btn-*` control
  classes with token-backed outline and `shadow-focus` treatment.
- The authenticated shell must expose a skip-to-content link that targets the
  main landmark before navigation chrome.
- Shared status affordances must use Lucide icons or text, not unicode glyphs
  such as checkmarks, warning signs, or arrows as icon substitutes.
- Data-dense reports and tables should reserve their expected shape with
  token-backed skeleton placeholders while loading; use spinner-only states for
  small inline actions, not full report/table surfaces.
- Evidence-lineage drawers should render graph responses as an ordered
  source-to-report path. Each hop should expose compact source, confidence, and
  version badges when those fields are available, falling back to the node's
  entity type when a source field is absent.
- Dense trust and attention explanations must keep at least the normal
  `text-content-muted` contrast token unless a stronger contrast proof exists.
- Links from the `/attention` queue to review or processing destinations must
  append `from=attention`. Destination back-links must use that source marker to
  return to `/attention`, while preserving the existing notification or module
  fallback when the marker is absent.

- Dialog, sheet, toast, tab/navigation, and icon-only control changes need
  component tests for keyboard behavior, landmark/role semantics, accessible
  names, and live-region behavior where relevant.
- Route switchers that navigate pages must use navigation/list semantics with
  `aria-current`; only use ARIA tabs when focus stays in one page and the
  rendered tab panels are controlled by the tablist.
- Future visual smoke coverage should include representative desktop and mobile
  routes, assert stable visible anchors, capture a nonblank screenshot, and keep
  document-level horizontal overflow at zero.
- Broader pixel-regression baselines may be added later, but they do not replace
  the required Playwright smoke path for app shell, accounts, statements, and
  review surfaces.

### Applied In

- `app/(main)/accounts/page.tsx`
- `app/(main)/statements/page.tsx`
- `playwright/ui-visual-smoke.spec.ts`
- `src/__tests__/uiPrimitives.test.tsx`
- `src/__tests__/accountsPage.test.tsx`
- `src/__tests__/statementsPage.test.tsx`

## 6. API Integration

All API calls must go through the centralized `apiFetch` or `apiUpload` utility in `lib/api.ts`.

**Rules:**
- **NO Direct `fetch()`**: Never use the native `fetch()` API for internal `/api/*` calls.
- **Authorization**: The utility automatically injects the `Bearer <token>` header from local storage.
- **Absolute URLs**: Use the `APP_URL` constant from `lib/api.ts` when you need to refer back to the frontend domain.

## 7. Monetary Amounts

Frontend monetary display and arithmetic must use `decimal.js` through `src/lib/currency.ts`.

**Rules:**
- Do not convert money with `Number()`, `parseFloat()`, or `toFixed()` in page/component code.
- Use `formatCurrencyLocale()` for currency display; it formats from Decimal/string values without JS number precision loss.
- Use `formatQuantity()` for portfolio and asset quantities; page/component code must not parse Decimal quantity strings through JS `number`.
- Use `sumAmounts()`, `subtractAmounts()`, `compareAmounts()`, and `toDecimal()` for monetary calculations and comparisons.
- Shared API types must represent decimal-bearing payload fields with `MoneyValue` or `DecimalValue`, not bare `number` field declarations.
- `MoneyValue` and `DecimalValue` are serialized strings at the API boundary. Components may accept `number` only at rendering/chart boundaries after explicit conversion through `src/lib/currency.ts`.
- Do not calculate or display cross-currency allocation percentages from raw nominal amounts. Show per-currency amounts until the backend provides a single-currency FX-converted total.
- Chart geometry may use `amountToChartNumber()` because chart libraries require `number` coordinates; do not reuse chart numbers for accounting totals or displayed money.

## 8. Responsive Navigation

Desktop sidebar and mobile drawer navigation share `components/navigation.ts` as the route source of truth.

**Rules:**
- Add primary workflow routes once in `primaryWorkflowNavItems` and drill-down
  routes once in `advancedNavItems`.
- Add workspace tab labels/icons once in `ROUTE_CONFIG`.
- Mobile must not render desktop workspace tabs; phone navigation uses the drawer only.
- Do not create separate reduced mobile menus that hide core routes.

## 9. Mobile Review Surfaces

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

## 10. App Metadata & PWA Head Tags

Root app metadata lives in `app/layout.tsx`.

**Rules:**
- Keep PWA manifest and icon metadata in the `metadata` export.
- Keep viewport-related fields, including `themeColor`, in the `viewport` export.
- Use `appleWebApp` for iOS web-app capability metadata; do not duplicate
  `apple-mobile-web-app-capable` in `metadata.other`.

## 11. Security & Authentication

- **AuthGuard**: Protects all `(main)` routes. Unauthorized users are redirected to `/login`.
- **Public Routes**: Only `/login` and `/ping-pong` are exempt from `AuthGuard`.
- **Injection Protection**: The `apiFetch` wrapper is the primary defense against missing user context.

## 12. Shared Types

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

## 13. Brokerage Import Completion Path

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

## 14. Dashboard First-Run Onboarding

The Dashboard must give first-time users a direct path into the core flow instead of only rendering empty metrics.

### Code References

- `app/(main)/dashboard/page.tsx` — onboarding detection and links
- `src/__tests__/dashboardPage.test.tsx` — AC16.12.17–AC16.12.19 coverage
