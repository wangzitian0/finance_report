# EPIC-022 PR12+ — PWA Bottom-Tab IA (Low-Fidelity Design)

> **Vision Anchor**: `decision-2-event-middle-layer`, `decision-4-two-stage-review`.
>
> Status: **design / pre-AC** (low-fidelity, approved direction; ACs land separately).
> Parent: [EPIC-022 Everyday-User IA](./EPIC-022.everyday-user-ia.md). This is the
> next slice that **finishes EPIC-022's own thesis**: EPIC-022 collapsed the
> accounting machinery into a 9-item **Advanced** drawer (a stated Non-Goal kept
> them "reachable via Advanced"); the app still feels information-overloaded
> because those machines remain standing navigation verbs. This slice pushes the
> machinery **out of navigation** into the already-built attention inbox plus an
> on-demand **Audit** hub, and flips the app to **mobile / PWA-first**.

## Problem

- 34 routes; navigation exposes **3 primary peers + a 9-item Advanced drawer**.
- The drawer is a junk drawer mixing three unlike categories: an investor domain
  (Portfolio), pure internal machinery (Journal / Reconciliation / Processing /
  Confidence), and one-time setup (3 separate Settings pages).
- The Home page is ~827 lines rendering ~10 widgets.
- Desktop-sidebar-first; mobile is an afterthought (`MobileNav`), yet checking
  personal finances is a phone activity.

## Principle

Only **destinations the user chooses to visit** belong in navigation. **Work the
system pushes to the user** belongs in one attention inbox (the bell) and inline,
in context. Verification ("is this number real?") is **browse-on-demand**, not a
routine the user performs every visit.

## Target IA — one model, two form factors

Mobile (primary): a bottom tab bar with five hit targets. Desktop (≥md): the
left sidebar mirrors the **same** five destinations. PWA-installable, safe-area
aware (reuse `pwa-safe-area-shell`).

```
🏠 Home     💬 Chat     ⊕ Add     🔍 Audit     ⋯ More
```

### ① 🏠 Home — "your money at a glance"
```
┌ Home ───────────────────────── 🔔3 ─┐   bell = attention inbox (/attention)
│ Net worth    S$ 123,456    ▲ 2.1% MoM │
│ "You're on track."                     │   plain-language verdict
│ ▸ 1 thing needs you: Review 2 stmts → │   single next-action (from inbox)
│ ┌ Balance │ Income │ Cash ┐           │   three statements = segmented control
│ │  Assets 123,456 · Liab -5,000  │    │   compact summary per statement
│ └──────────────────────────────┘     │
│ [ Full report ↗ ]                     │   → /reports/{balance-sheet|...}
│ [ Show trends & breakdown ⌄ ]         │   opt-in: charts, AdvisorBrief, etc.
└────────────────────────────────────────┘
```
- The bell (top-right) is the inbox: reuse `WorkflowNotificationCenter` +
  `/attention` (already built in EPIC-022 AC22.6).
- Three statements live as a segmented control inside Home; each segment shows a
  compact summary and a "Full report" deep-link to the existing detail page.
- Heavy charts / advisor brief are opt-in (progressive disclosure).

### ② 💬 Chat — AI advisor
Existing `/chat`, promoted to a first-class tab. Full-screen conversational
surface; no structural redesign.

### ③ ⊕ Add (center) — bottom sheet, not a page
```
   Add ─────────────────────────
   📄 Upload statement   PDF / CSV / image — the AI identifies the type
   ✏️ Manual entry / edit ESOP · property · cash adjustment …
```
- "Upload statement" → the shipped three-entry uploader (PR #1521); CSV remains
  a fold within it.
- "Manual entry / edit" → `GuidedEvidenceForm`.

### ④ 🔍 Audit — first-class "see the books behind your numbers" hub (new `/audit`)
Aggregates three existing machines into one verify-on-demand surface, reframed
for a non-accountant:
```
┌ Audit ── "Everything behind your numbers." ──────────┐
│ ◉ Trust          32 trusted · 2 confirm · 1 low      →│  ← /confidence
│ ◉ Reconciliation 98% matched · 1 unmatched S$540     →│  ← /reconciliation(+unmatched)
│ ◉ Journal        1,204 entries · browse ledger       →│  ← /journal
│ ◉ Processing     all done                            →│  ← /processing
└────────────────────────────────────────────────────────┘
```
- Each card deep-links to the existing page; those pages stay and gain a
  back-link to `/audit`.
- Extra entry: tapping any figure in Home / Reports drills into the Journal
  filtered to that account ("show the entries behind this").
- Overlap with the inbox is intentional and benign: the **inbox** is "act on
  what needs me now" (push); **Audit** is "browse to verify on demand". The same
  unmatched item appears in both, with different intent.

### ⑤ ⋯ More — low-frequency overflow
```
👤 user@email
💼 Portfolio   shown only when the user holds securities (tabs: holdings/prices/evidence)
⚙️ Settings    merged into one page (tabs: general / AI / LLM)
🛠️ Advanced    genuine power/dev escape hatch (anything left)
🚪 Logout
```

## Route disposition (delta vs EPIC-022 as delivered)

| Disposition | Routes |
|---|---|
| **Redesign** | `/` (Home: net-worth + 3-statement segments + bell); `/settings/*` → merged `/settings` |
| **New** | `/audit` hub; bottom tab-bar component; ⊕ Add bottom sheet |
| **Folded into Audit** | `/journal`, `/reconciliation` (+`/unmatched`, `/review-queue`), `/confidence`, `/processing` (pages kept + back-link to `/audit`) |
| **Folded into More** | `/portfolio*` (conditional), `/accounts`, Advanced |
| **Inbox (reuse)** | `/attention`, `WorkflowNotificationCenter` (the bell) |
| **Delete / redirect** | `/statements/upload` → `/upload`; `/assets` → `/portfolio`; `/events` → `/notifications` |
| **Unchanged** | `/statements/[id]` (+`/review`), `/login`, `/ping-pong` (dev) |

## Build sizing

- **New**: bottom tab bar (replaces `MobileNav`); ⊕ Add sheet; `/audit` hub;
  merged `/settings` page.
- **Reconfigure**: `navigation.ts` restructure; desktop `Sidebar` mirrors the new
  IA; conditional Portfolio; route redirects.
- **Pure reuse**: `/attention` inbox; the bell; `GuidedEvidenceForm`; the
  three-entry uploader; the existing journal / reconciliation / confidence /
  processing pages.

Net new *business logic* is modest — most surfaces recompose existing pages. The
main effort multipliers are (a) the new-page test coverage against the repo's
98% frontend gate and (b) rewriting E2E specs that currently click sidebar items
to instead route via the bottom bar / inbox / Audit hub.

## Open questions

1. **Audit vs Verify** — tab label. "Audit" is accurate but mildly jargon-y;
   "Verify" reads friendlier to a non-accountant. Default: keep **Audit**, with
   the subtitle "see the books behind your reports".
2. **`/accounts`** placement — chart-of-accounts is accounting structure; goes
   under **More → Advanced** (default) or could sit inside Audit.
3. **Desktop form factor** — sidebar mirrors the 5 destinations; the ⊕ Add
   becomes a button. Bottom bar is mobile-only.
4. **WorkspaceTabs** (the browser-style tab strip in the header) is extra chrome;
   out of scope for this slice, revisit separately.

## Non-Goals

- Removing the deep accounting pages — they remain reachable from Audit and from
  inbox deep-links (consistent with EPIC-022).
- Backend schema changes — this slice is frontend IA + recomposition.
