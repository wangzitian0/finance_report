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

The matrix `proofs` section is a **generated artifact**, not a hand-maintained
list. Its source of truth is a co-located `@ac_proof(...)` decorator on each
critical-proof test (`common/testing/ac_proof.py`);
`tools/generate_critical_proof_matrix.py` statically scans those decorators and
emits the YAML, and `--check` fails CI if the checked-in file drifts (exactly
like `tools/generate_ac_registry.py --check`). The macro `outcomes` section —
the README/EPIC outcome contract — stays hand-maintained in
`docs/ssot/critical-proof-outcomes.yaml` and is merged in verbatim. A PR
anchoring a new AC therefore edits only its own test file (adds the decorator);
two such PRs touching different tests do not collide on the central YAML.

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

## Cross-Cutting Index Artifacts: Two Kinds

Several SSOT files are *cross-cutting indexes* — one central file that many
independent PRs touch. Hand-maintaining them as one shared list makes
independent PRs collide textually (false sharing) and forces a linear merge
train. Every such artifact must be stored in one of two conflict-resistant
forms, chosen by what the file fundamentally *is*:

| Kind | What it is | Storage rule | Examples |
|---|---|---|---|
| **Derived index** | A projection of facts that already live somewhere else | Generate from the co-located source; check the result in as an artifact guarded by `--check` (fail CI on drift). A PR edits only the source (e.g. its own test/EPIC), never the index. | `ac_registry` / `infra_registry` (from EPIC docs), `critical-proof-matrix.yaml` (from `@ac_proof` decorators), `vision-proof-matrix.yaml` *(same class — migrate next)* |
| **Persisted ratchet** | A floor that must survive across runs and must NOT be regenerated from current state | Keep persisted, but store conflict-free: one sorted, line-oriented record per key, with `merge=union` in `.gitattributes` so PRs adding *different* keys auto-merge and only same-key edits conflict. | `ac-score-baseline.jsonl` |

The distinction is critical: regenerating a *derived index* is correct and
required; regenerating a *persisted ratchet* from current scores would erase the
floor it exists to protect. A new file that is a central index but stored as a
hand-maintained shared list is drift — convert it to the matching kind.

`docs/ssot/vision-proof-matrix.yaml` is the same-class **derived index** to look
to next: it is already generated from EPIC ACs by
`tools/generate_vision_proof_matrix.py --check`, but its rows are still derived
from EPIC AC tables rather than from co-located per-test declarations. Aligning
it with the `@ac_proof` co-location model (so its proof rows come from the tests
themselves) is tracked as follow-up and intentionally out of scope here.

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

The baseline report remains advisory. A metric becomes a gate only after the HLS
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
the changed-file list and a base git ref to compare the current change against
the already reported baseline without requiring immediate cleanup of unchanged
legacy debt.

The gate has two layers. The changed-surface layer enforces hard rules on files
and manifest entries touched by the current PR:

- changed SSOT files under `docs/ssot/` are expected to be owned by the current
  manifest
- newly added manifest entries are expected to declare `family`
- newly added entries with `kind: clause` are expected to declare `parent`
- changed high-risk or machine-owned manifest entries are expected to include a
  proof path in `proofs` or `cross_refs`
- high-risk changed SSOT files are expected to have at least one owner entry
  with a proof path

The trend layer compares protected per-system governance watermarks against the
base ref. `finance_report` and `infra2` are compared independently so one system
cannot mask the other. Protected ratios must be non-decreasing, and protected
debt counts must be non-increasing:

- manifest family coverage ratio
- manifest kind coverage ratio
- machine-owned proof coverage ratio
- high-risk proof coverage ratio
- missing family count
- missing kind count
- machine-owned entries missing proof count
- high-risk entries missing proof count

Historical findings from the report remain advisory until a later threshold
cleanup issue selects them explicitly, but the protected watermarks must not
move backward. The gate should not be used to force a large SSOT rewrite in
unrelated PRs.

## SSOT Governance Threshold Cleanup

Threshold cleanup is tracked by
[#824](https://github.com/wangzitian0/finance_report/issues/824). Cleanup PRs
select one metric threshold from the governance report, explain the exact
system and candidate set, and keep runtime behavior unchanged.

The first cleanup threshold is `finance_report.orphan_ssot_files == 0`. It
binds existing orphan SSOT files to parent concepts instead of promoting every
file into an independent HLS concept:

- `docs/ssot/observability-logging.md` is a child playbook of
  `observability_logging`.
- `docs/ssot/ac-score-baseline.jsonl` is a machine baseline artifact of
  `tdd_workflow`.

The second cleanup threshold is
`finance_report.machine_owner_entries_missing_proof == 0`. It migrates a small
representative set of machine-owned finance_report entries before attempting
bulk family/kind classification. A migrated SSOT entry must also be linked from
the related README, SSOT, EPIC, or vision entry points with the SSOT key as the
Markdown link label; otherwise the manifest entry is only registered, not
actively used as the source of truth:

- [`extraction_failed_case_registry`](./extraction-audit-failed-cases.yaml)
  declares `family: extraction`, `kind: registry`, its executable registry
  proof, and inbound links from the extraction SSOT and EPIC-003.
- [`source_coverage_matrix`](./source-coverage-matrix.yaml) declares
  `family: source`, `kind: matrix`, and both its validator and test proof, with
  inbound links from the extraction SSOT, EPIC-013, and vision routing.

Future cleanup slices should remain narrow and metric-selected. FR and infra2
cleanup should stay in separate PRs unless the selected finding is explicitly a
cross-system authority-boundary defect.

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
