## Summary

<!-- One-sentence description of what this PR does. -->

Closes #<!-- issue number -->

---

## Linked EPIC and ACs

| Field | Value |
|-------|-------|
| **EPIC** | EPIC-XXX — _Name_ |
| **AC IDs** | AC0.0.0, AC0.0.1 |
| **AC Registry updated** | `docs/ac_registry.yaml` / `docs/infra_registry.yaml` / N/A |

---

## SSOT Changes

<!-- List every docs/ssot/ file changed or created in this PR. Write "None" if purely code changes with existing SSOT coverage. -->

- [ ] `docs/ssot/MANIFEST.yaml` — added/updated concept(s): _list them_
- [ ] `docs/ssot/<file>.md` — _describe change_
- [ ] None — existing SSOT already covers this change

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
- [ ] `repo/` submodule updated for production config changes (if applicable)
- [ ] `tools/check_env_keys.py` passes (if env vars changed)
- [ ] `tools/check_manifest.py` passes (if SSOT files changed)
- [ ] `tools/lint_doc_consistency.py` passes

### CI/CD, Runtime, and VPS Infra Audit

Required when this PR changes workflows, deploy tooling, Dokploy runtime config,
VPS host scripts, or logs:

- [ ] Lifecycle ownership is unified: create/update/deploy/delete/cleanup/reconcile paths share one tool or explicitly documented owner.
- [ ] Logs do not print raw Dokploy API bodies, full env strings, tokens, `.env`, PEM content, or SSH keys.
- [ ] API/CLI diagnostics show only allowlisted effective-state diffs; unchanged and secret fields are not logged.
- [ ] VPS host hygiene is local to the VPS and does not require Dokploy, GitHub, or Vault credentials.
- [ ] Cleanup is scoped: PR-preview cleanup removes only the matching compose stack, matching compose volumes, and closed-PR leftovers.
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
