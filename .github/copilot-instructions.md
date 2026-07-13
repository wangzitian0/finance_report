# GitHub Copilot Instructions for Finance Report

**Read [AGENTS.md](../AGENTS.md) first** — it is the authoritative agent guide:
red lines, work order, branch/PR rules, and the navigation map to everything
else.

Before every commit/push, run the pre-push parity check — see AGENTS.md § Pre-Push Gate Parity.

This file deliberately holds **no project facts** (stack versions, paths,
model names, thresholds). A duplicated-facts file drifts silently and feeds
auto-review wrong context — this one previously claimed Next.js 14, a retired
auth library, and non-existent frontend paths. Facts live with their owners:

- Product goal & culture → [`vision.md`](../vision.md)
- Shared contracts & vocabulary → [`docs/ssot/`](../docs/ssot/README.md)
  (routed by `docs/ssot/MANIFEST.yaml`)
- Security & integrity hard stops → [`docs/agents/red-lines.md`](../docs/agents/red-lines.md)
- Tech stack & commands → [`README.md`](../README.md)

Review guidance: hold PRs to the red lines (Decimal for money, balanced
entries, explicit `sa.Enum` names, no raw `fetch()` in frontend, no real
financial data in any artifact) and to the work order (AC-anchored tests
before code). All output in English.
