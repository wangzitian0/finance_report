# Agent Orchestration

> **SSOT Key**: `agent_orchestration` | Deliverable contract, work order, and delegation rules.

## Agent Deliverable Contract

Agents deliver a mergeable branch/PR (never commit directly to `main`):
- Cleanly mergeable onto `main` (`mergeable: MERGEABLE`, `mergeStateStatus: CLEAN` or `BEHIND` within 24h per [branch-policy.md](../contributing/branch-policy.md) §4).
- All CI required checks green (`finish` passes; watch runs to completion).
- Every review comment fixed or justified and replied on the thread before resolving. (Escalate for a fresh review pass after resolving >=1 High or >=3 Medium findings.)
- Code, commits, and PR descriptions written in English.
- Only production deployments (`release.yml` / `infra2 deploy` with `type=prod`) require owner approval and presence.

## Development Work Order (TDD-First)

1. **MECE**: Split work into non-overlapping slices.
2. **AC**: Register active `AC-<pkg>.<group>.<seq>` in `common/<pkg>/contract.py` (`roadmap`) — never mirror package ACs into `docs/project/EPIC-*.md` tables ([common/meta/migration-standard.md](../../common/meta/migration-standard.md)).
3. **Test**: Write failing tests first referencing AC IDs with synthetic/anonymized fixtures ([red-lines.md](./red-lines.md)).
4. **Code & Doc**: Implement minimal code and update the owning package `readme.md` / `contract.py`.

Never hand-author LLM cassettes under `tests/fixtures/llm_cassettes/` (always record with `make llm-record`).

## Cross-Cutting Contract Reminders

- Explicit `name="..."` on every `sa.Enum` ([common/meta/schema.md#enum-naming](../../common/meta/schema.md#enum-naming)).
- Separate `infra2` PR when adding production env vars or changing Vault/Compose templates.
- Clean up superseded code, config, tests, and docs in the same PR.

Related: [red-lines.md](./red-lines.md) · [branch-policy.md](../contributing/branch-policy.md) · [common/testing/tdd.md](../../common/testing/tdd.md)
