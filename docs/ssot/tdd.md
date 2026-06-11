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

`vision.md` owns the product's north-star goal, culture, and decision filters —
not a status or acceptance document.

## Acceptance Criteria

AC IDs use `ACx.y.z`:

| Part | Meaning |
|---|---|
| `x` | EPIC number |
| `y` | feature block within the EPIC |
| `z` | acceptance criterion within the block |

Registry generation is code-owned by `tools/generate_ac_registry.py`.
`docs/ac_registry.yaml` and `docs/infra_registry.yaml` are small generated
indexes. Runtime tools materialize entries from EPIC markdown plus
`docs/ac_registry_overrides.yaml`, which preserves deprecated or non-derived
historical entries without making the indexes hand-edited truth.

```bash
python tools/generate_ac_registry.py --check
```

Registry files:

- `docs/ac_registry.yaml` — feature index
- `docs/infra_registry.yaml` — infra index
- `docs/ac_registry_overrides.yaml` — explicit override entries that are not
  derived from current EPIC text

Do not edit generated index files manually. Add or update active AC definitions
in the owning EPIC; use the override file only for intentional historical,
deprecated, or non-derived metadata.

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

Product E2E tests have an additional EPIC ownership rule: every `test_*`
function under product E2E roots must carry at least one `EPIC-xxx` ID in the
test function name or function docstring, and every `docs/project/EPIC-*.md`
file must be referenced by at least one such test. The same gate validates the
root README EPIC map against `docs/project/EPIC-*.md` and fails unclassified
E2E-like assets outside declared product or non-product roots.
`tools/check_e2e_epic_traceability.py` enforces this closure in CI.

Core product journeys have one extra guard:
`docs/ssot/critical-proof-matrix.yaml`. It owns the macro README -> EPIC -> E2E
contract for the closed set of core vision outcomes. The checker keeps the
README outcome table, matrix rows, owner EPIC reverse declarations, and explicit
E2E proof anchors in sync. It is not a general-purpose semantic parser for all
tests.

## Proof Semantics

| Category | Counts as proof? | Notes |
|---|---|---|
| Behavioral unit/integration/E2E test with assertions | Yes | Preferred |
| Contract test that validates schema or workflow behavior | Yes | Good for API/state contracts |
| Generated report reference without test behavior | No | Traceability only |
| `_ac_stubs` reference | No | Fails mandatory AC gate |
| `expect(true).toBe(true)` or pure `pass` | No | Placeholder debt |
| `tests/tooling` registered AC reference | Yes | Tooling/CI behavior proof; synthetic fixture IDs are excluded from invalid-ref counts |
| Strikethrough deprecated AC | Not required | Excluded from active coverage and untested counts |
| Manual verification | Not automated proof | Convert or mark as explicit manual gate |

For critical proof matrix rows, behavioral proof must be a product test anchor,
not a broad contract bucket. Static/doc checks and manual gates may be listed in
the matrix only when they are explicitly labeled as such; they do not satisfy a
behavioral row.

Macro and micro proof are intentionally separate:

- **Macro**: README -> EPIC -> E2E, owned by
  `docs/ssot/critical-proof-matrix.yaml` and enforced bidirectionally by
  `tools/check_critical_proof_matrix.py`.
- **Micro**: EPIC -> AC -> test, owned by EPIC AC tables, generated registries,
  and AC traceability gates.

## SSOT Governance Metrics

`tools/report_ssot_governance.py` owns report-only SSOT governance metrics for
the finance_report SSOT manifest and the checked-out infra2 SSOT manifest. It
reads finance_report `concepts` and infra2 `entries` without requiring a shared
manifest schema, then publishes advisory metrics in CI.

The report measures:

- total entries and owner count by system
- duplicate owners and orphan files under `docs/ssot/`
- explicit `family`, `kind`, `parent`, and `authority` field coverage
- inferred family distribution for legacy entries without explicit fields
- machine-owned entries that do not yet have proof links
- high-risk entries that do not yet have proof links
- future gate candidates with samples

These metrics are not hard gates. A metric may become a gate only after the HLS
design defines the target model, the report has established a stable baseline,
and a gradual-gate issue defines a threshold and rollout scope.

Tracked by
[#821](https://github.com/wangzitian0/finance_report/issues/821),
[#822](https://github.com/wangzitian0/finance_report/issues/822), and
[#823](https://github.com/wangzitian0/finance_report/issues/823).

## SSOT Governance Gates

`tools/report_ssot_governance.py --fail-on-gate` owns the incremental
prevent-worse gate tracked by
[#823](https://github.com/wangzitian0/finance_report/issues/823). The gate uses
the changed-file list and a base git ref to compare only the current change
against the already reported baseline.

The first gate version enforces only changed surfaces:

- changed SSOT files under `docs/ssot/` are expected to be owned by the current
  manifest
- newly added manifest entries are expected to declare `family`
- newly added entries with `kind: clause` are expected to declare `parent`
- changed high-risk or machine-owned manifest entries are expected to include a
  proof path in `proofs` or `cross_refs`
- high-risk changed SSOT files are expected to have at least one owner entry
  with a proof path

Historical findings from the report remain advisory until a later threshold
cleanup issue selects them explicitly. The gate should not be used to force a
large SSOT rewrite in unrelated PRs.

Intentional temporary debt uses
`docs/ssot/governance-exceptions.yaml`. Each exception targets one finding, for
example `finance_report:manifest:temporary_concept` or
`infra2:docs/ssot/example.md`, and links the GitHub issue that removes it. The
exception file is reviewed like code; prose comments in PRs are not an
exception path.

Manual verification cleanup is tracked in
[issue #454](https://github.com/wangzitian0/finance_report/issues/454).
Invalid AC references are reported by
`python tools/analyze_test_ac_coverage.py --no-write --stdout` and CI
traceability artifacts.
AC-to-EPIC mismatch triage is reported by
`python tools/audit_ac_epic_mismatches.py`, which separates actionable refs
from fixture-only fake IDs.

Current coverage enforcement:

- Backend pytest local source-coverage threshold is code-owned by
  `apps/backend/pyproject.toml` (`--cov-fail-under`).
- Unified coverage is a no-regression baseline gate from
  `unified-coverage.json`, not a hand-written fixed percentage in this TDD doc.
- Branch coverage tracking is enabled for backend tests.
- CI merges coverage across shards and validates the unified baseline before the
  overall CI gate passes.

## Required Local Checks

Use these before claiming a documentation or implementation change is aligned:

```bash
python tools/generate_ac_registry.py --check
python tools/analyze_test_ac_coverage.py --no-write --stdout
python tools/check_e2e_epic_traceability.py
python tools/check_critical_proof_matrix.py
python tools/check_manifest.py
python tools/check_ssot_ownership.py
```

Coverage is governed by `docs/ssot/coverage.md` and
`common/coverage/policy.py`. The current policy is no-regression from
`unified-coverage.json`; this TDD document intentionally links to code-owned
thresholds instead of copying mutable percentage values.

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
- process checks -> tests/tooling/CI gates

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

- [Root README](https://github.com/wangzitian0/finance_report/blob/main/README.md)
- [Coverage SSOT](./coverage.md)
- [CI/CD SSOT](./ci-cd.md)
- `python tools/analyze_test_ac_coverage.py --no-write --stdout`
