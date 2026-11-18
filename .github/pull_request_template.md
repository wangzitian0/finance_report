## Summary

<!-- One-sentence description of what this PR does. -->

Closes #<!-- issue number -->

---

## Linked EPIC and User Cases

| Field | Value |
|-------|-------|
| **EPIC** | EPIC-XXX — _Name_ |
| **User Cases** | UC-XX / N/A |
| **Package docs updated** | `common/<pkg>/readme.md` / N/A |

---

## SSOT Changes

<!-- List every package readme.md or user_cases_ssot.json concept changed or created in this PR. Write "None" if purely code changes with existing coverage. -->

- [ ] `common/meta/flows/user_cases_ssot.json` — added/updated user case(s): _list them_
- [ ] `common/<pkg>/readme.md` — _describe change_
- [ ] None — existing package docs already cover this change

---

## TDD Evidence

<!-- Paste the commit SHA of the failing test (red phase) written BEFORE the implementation. -->

| Phase | Commit SHA | Description |
|-------|-----------|-------------|
| 🔴 Red (failing test) | `abc1234` | `test_<name> fails with NotImplementedError` |
| 🟢 Green (passing test) | `def5678` | `implement <name>: tests pass` |

---

## Engineering Audit

- [ ] `sa.Enum` instances all have explicit `name="..._enum"` parameter
- [ ] `NEXT_PUBLIC_` variables added to `apps/frontend/Dockerfile` `ARG`/`ENV` (if applicable)
- [ ] Separate infra2 PR linked for production Vault/Compose changes (if applicable)
- [ ] `tools/check_env_keys.py` passes (if env vars changed)
- [ ] `apps/backend/.venv/bin/python tools/preflight.py --tier=static` passes
- [ ] No real financial data — amounts, balances, account numbers, holder names, local paths, or real statement filenames are redacted or generated/anonymized.

### CI/CD, Runtime, and VPS Infra Audit

Required when this PR changes workflows, deploy tooling, Dokploy runtime config,
VPS host scripts, or logs:

- [ ] Lifecycle ownership is unified: create/update/deploy/delete/cleanup/reconcile paths share one tool or explicitly documented owner.
- [ ] Logs do not print raw Dokploy API bodies, full env strings, tokens, `.env`, PEM content, or SSH keys.
- [ ] API/CLI diagnostics show only allowlisted effective-state diffs; unchanged and secret fields are not logged.
- [ ] VPS host hygiene is managed by a Dokploy server schedule and does not require GitHub SSH or Vault credentials.
- [ ] Cleanup is scoped: PR cleanup removes only GHCR PR artifacts; Docker volume/container leftovers are handled by the Dokploy host hygiene schedule.
- [ ] Proof command includes focused tests for redaction, lifecycle cleanup, and host hygiene.

---

## Testing

<!-- Describe how to verify this PR works. Include specific test commands. -->

```bash
# Run relevant tests
moon run :test -- tests/<domain>/test_<file>.py

# Lint check
moon run :lint
```

---

## Screenshots / Evidence

<!-- For UI changes: attach before/after screenshots. For backend: paste relevant log snippets or test output. -->

_N/A_
