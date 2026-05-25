# EPIC -> AC -> Test Workflow

> **SSOT Key**: `tdd-transformation`

This document defines the workflow that connects project scope to executable
proof. Current status metrics are owned by generated reports or code-owned
checks; the root `README.md` links to those sources instead of duplicating their
mutable values. This document owns the process.

## Canonical Hierarchy

```text
README.md -> docs/project/EPIC-*.md -> docs/*_registry.yaml -> tests
```

1. **README** summarizes project status and links to generated proof.
2. **EPIC** documents define scope and acceptance criteria.
3. **AC registries** are generated from EPIC documents.
4. **Tests** prove behavior.

`vision.md` is a decision filter, not a status or acceptance document.

## Acceptance Criteria

AC IDs use `ACx.y.z`:

| Part | Meaning |
|---|---|
| `x` | EPIC number |
| `y` | feature block within the EPIC |
| `z` | acceptance criterion within the block |

Registry generation is code-owned by `scripts/generate_ac_registry.py`.
Registry YAML is grouped by `ACx -> ACx.y` so unrelated scenarios do not share
one append point. The files do not commit a mutable total; CI computes counts
from the grouped entries.

```bash
python scripts/generate_ac_registry.py --check
```

Generated registry files:

- `docs/ac_registry.yaml`
- `docs/infra_registry.yaml`

Do not edit registry files manually.

## Test References

Tests should reference AC IDs in the first line of the test docstring or test
name. A reference makes the test discoverable, but it is not by itself
behavioral proof.

Good:

```python
def test_balanced_entry_is_rejected_when_debits_do_not_equal_credits():
    """AC2.2.2: Unbalanced entry fails validation."""
    ...
```

Not sufficient:

```typescript
it("AC17.7.1 placeholder", () => {
  expect(true).toBe(true);
});
```

The CI AC traceability gate fails mandatory ACs that are missing,
placeholder-only, or stub-only before the traceability audit artifact is
generated.

## Proof Semantics

| Category | Counts as proof? | Notes |
|---|---|---|
| Behavioral unit/integration/E2E test with assertions | Yes | Preferred |
| Contract test that validates schema or workflow behavior | Yes | Good for API/state contracts |
| Generated report reference without test behavior | No | Traceability only |
| `_ac_stubs` reference | No | Fails mandatory AC gate |
| `expect(true).toBe(true)` or pure `pass` | No | Placeholder debt |
| Manual verification | Not automated proof | Convert or mark as explicit manual gate |

Manual verification cleanup is tracked in
[issue #454](https://github.com/wangzitian0/finance_report/issues/454).
Invalid AC references are reported by
[../analysis/test-ac-coverage-report.md](../analysis/test-ac-coverage-report.md).
AC-to-EPIC mismatch triage is reported by
[../analysis/ac-epic-mismatch-report.md](../analysis/ac-epic-mismatch-report.md),
which separates actionable refs from fixture-only fake IDs.

Current coverage enforcement:

- Backend pytest keeps a 90% local source-coverage threshold.
- Unified coverage is a no-regression baseline gate from
  `unified-coverage.json`, not a hand-written fixed percentage in this TDD doc.
- Branch coverage tracking is enabled for backend tests.
- CI merges coverage across shards and validates the unified baseline before the
  overall CI gate passes.

## Required Local Checks

Use these before claiming a documentation or implementation change is aligned:

```bash
python scripts/generate_ac_registry.py --check
python scripts/analyze_test_ac_coverage.py --stdout
python scripts/check_manifest.py
python scripts/check_ssot_ownership.py
```

Coverage is governed by `docs/ssot/coverage.md` and
`scripts/coverage_policy.py`. The current policy is no-regression from
`unified-coverage.json`; there is no fixed 96% unified gate at the time of this
writing.

## Development Workflow

For feature work:

1. Anchor the work to an EPIC.
2. Add or update ACs in the EPIC document.
3. Regenerate/check registries.
4. Write a failing behavioral test that references the AC.
5. Implement the smallest change that passes the test.
6. Update docs only to explain rationale and link to code/test owners.

For documentation-only work:

1. Do not invent new implementation facts in prose.
2. Link to code owners, generated contracts, or tests.
3. If a fact is not code-owned yet, create an issue and reference it.

## Code-Owned Documentation Direction

The long-term target is to move facts out of prose when they can be enforced by
code:

- thresholds and constants -> code/config/common package
- API shapes -> schemas/OpenAPI/generated client
- state machines -> code-owned transition model plus tests
- process checks -> scripts/tests/CI gates

Tracked by
[#453](https://github.com/wangzitian0/finance_report/issues/453).

## Generated Status

README project metrics should be generated or validated from registries and
test reports. Tracked by
[#455](https://github.com/wangzitian0/finance_report/issues/455).

Do not hand-write mutable status snapshots in prose documentation. AC counts,
coverage percentages, issue state, PR state, CI status, dependency versions,
and test inventories belong to generated reports, GitHub, lockfiles, CI, or
mechanically validated matrices.

## Related

- [Root README](../../README.md)
- [Coverage SSOT](./coverage.md)
- [CI/CD SSOT](./ci-cd.md)
- [AC coverage report](../analysis/test-ac-coverage-report.md)
