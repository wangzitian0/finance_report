# Frontend Patterns & Architecture

Single source of truth for Next.js frontend conventions (`apps/frontend/`).

## 1-3. SSR, Mounted State & Theme System

Client storage hooks (`useWorkspace`) guard hydration with `mounted` state (`apps/frontend/src/components/ui/index.tsx`). Colors, spacing, radius, shadows, layers, and motion use CSS variables (`apps/frontend/src/app/globals.css`, `apps/frontend/tailwind.config.ts`) rather than hardcoded palette utilities.

## 4. Design Tokens

`apps/frontend/src/app/globals.css` and `apps/frontend/tailwind.config.ts` map light/dark theme variables to semantic Tailwind classes:

```text
/* Prefer token classes (e.g. bg-surface-card text-content-muted border-border) */
```

### Token Families

- **Surface & content**: `surface`, `surface-card`, `surface-muted`, `content`, `content-muted`, `content-inverse`.
- **Border colors**: Use `border-border` and `border-hover` instead of `border-[var(--border)]`.
- **Accent & status**: `accent`, `accent-hover`, `accent-muted`; `status-success`, `status-warning`, `status-error`, `status-info`.
- **Chart, scale, elevation & layers**: `chart-1..5`, `text-caption/body/title`, `page/panel/control`, `rounded-control/panel/pill`, `shadow-card/floating/focus`, `z-drawer/overlay/modal/toast`, `duration-fast/standard/slow`.

### Page-Local Visual Decisions

- Login uses the accent gradient for its primary submit button (`--accent` -> `--accent-hover`).
- Dashboard cards and chart panels use the shared `card` class with tokenized radius and `shadow-card`.

## 5. UI Primitives & Accessibility

Use shared primitives in `apps/frontend/src/components/ui/index.tsx` (`Button`, `IconButton`, `Badge`, `Alert`, `EmptyState`, `LoadingState`, `PageHeader`, `ProvenanceBadge`, `ConfidenceBadge`).

### Global Accessibility Baseline

- `apps/frontend/src/app/globals.css` enforces `prefers-reduced-motion: reduce` and `:focus-visible` outlines (`outline: 2px solid var(--accent)`, `shadow-focus`) across controls and skip-link targets.
- Use Lucide icons/text rather than Unicode glyphs, keep human copy free of internal jargon (`apps/frontend/src/__tests__/designTokens.test.tsx`), and preserve `/audit` (`?from=attention`) return links.

### Mobile Install Baseline

- The app shell owns Add to Home Screen prompts via `InstallAppPrompt`; business pages must not listen for `beforeinstallprompt`.
- Keep standalone safe-area padding (`.pwa-safe-area-shell`) and zero horizontal overflow on 375–390 px viewports.

## 6-8. API Integration, Shared Layers & Monetary Amounts

- **Transport (`apps/frontend/src/lib/api.ts`)**: All internal `/api/*` calls use `apiOperation`, `apiOperationUpload`, `apiOperationDownload`, or `apiOperationStream` with HttpOnly cookie credentials (`credentials: "include"`). Never call native `fetch()` directly outside `lib/api.ts`. Handle errors via `ApiError.errorId`, and read GET endpoints via React Query shared keys (`useApiQuery`).
- **Types (`apps/frontend/src/lib/types.ts`)**: Generated from `apps/frontend/openapi.json` via `npm run gen:api-types`.
- **Layers (enforced downward)**: `app/(main)/**/page.tsx` (<300 lines) -> `components/<feature>/*` -> `hooks/*` -> `lib/api.ts` -> `lib/types.ts` -> `components/ui/*` -> `lib/audit/{money,quantity,ratio}`.
- **Decimal precision**: Format and compute all monetary values and quantities via `lib/audit/money` and `lib/audit/quantity`, never JS `Number()`/`parseFloat()`/`toFixed()`. See: common/ledger/readme.md#decimal-rule

## 9-12. Navigation, Security & Auth

- `apps/frontend/src/lib/route-map.json` owns routes (`10 target`, `2 shell`, `27 redirect`); bottom tab bar and desktop sidebar expose 5 shared targets (`Home`, `Chat`, `Add`, `Audit`, `More`).
- `AuthGuard` protects `(main)` routes (only `/login` is public). `apps/frontend/src/lib/auth.ts` stores non-secret user metadata only; auth tokens stay in the HttpOnly cookie. CSP headers forbid `unsafe-eval` (`frame-ancestors 'none'`).
