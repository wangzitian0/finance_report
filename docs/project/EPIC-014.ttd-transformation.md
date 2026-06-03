# EPIC-014: Test-Driven Documentation (TTD) Transformation

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, generated reports, and executable checks.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Phase**: Tooling Enhancement (Phase 3-5)
> **Duration**: 3-4 weeks
> **Owner**: Development Team
>
> **2026-05-25 alignment note**: Current proof metrics are owned by generated
> reports and executable checks; the root [README](../../README.md) links to
> those sources instead of duplicating mutable values. This EPIC owns the TTD
> transformation scope; code/test migration follow-ups are tracked by issues
> #452, #453, #454, #455, and #456.

## 📌 Executive Summary

Transform the project's documentation approach from **prescriptive** (MUST/REQUIRE statements) to **descriptive** (design principles + automated enforcement). The goal is to make **tests and tools the single source of truth** for constraints, while documentation focuses on **why** and **how** rather than **what is mandatory**.

### Core Philosophy

| Old Approach (Prescriptive) | New Approach (TTD) |
|---------------------------|-------------------|
| Documentation says "MUST do X" | Tests fail if X is not done |
| SOP is a checklist document | SOP is an automated tool |
| "What to do" in prose | "What to do" in automated checks |
| Manual verification required | CI enforces rules automatically |
| Documentation drift possible | Tests = truth, docs = guidance |

## 🎯 Success Criteria

### Must Have (P0)
- [x] All `MUST`/`REQUIRE` statements removed from documentation
- [x] All constraint references point to tests (e.g., `See: tests/accounting/test_decimal_safety.py`)
- [x] Every SOP has at least one automated tool backing it
- [x] Pre-commit hooks enforce all static constraints
- [x] CI pipeline enforces all runtime constraints
- [x] No manual checklist processes remaining

### Nice to Have (P1)
- [ ] Interactive tool guide for new developers (`make help` covers 90%)
- [ ] Automated PR checks for documentation-test alignment
- [ ] SOP tools have `--dry-run` mode for preview
- [ ] Documentation includes "Why this constraint exists" sections

### Not Acceptable
- [ ] Constraints enforced only by documentation prose
- [ ] SOP is a markdown checklist without automation
- [ ] Test failures without corresponding documentation references
- [ ] Manual verification required for common operations

---

## 📊 Historical State Analysis Snapshot

The tables in this section are retained as transformation context. They are not
the live source for current tool coverage, CI behavior, or documentation
status.

### Existing Constraint Enforcement

 | Mechanism | Type | Coverage | Gap |
|-----------|------|----------|-----|
| **Pre-commit Hooks** | Static | Ruff, mypy, file hygiene, env consistency, frontend lint, schema validation | Missing: Dockerfile lint, dependency security |
| **CI Pipeline** | Runtime | Backend tests (>=95% coverage), frontend build, E2E smoke tests | Missing: Performance checks, dependency freshness |
| **Test-Based Constraints** | Test | Decimal safety, Enum naming, accounting equation | Missing: Migration length, dependency security |
| **Env Validation** | Config | `check_env_keys.py` validates 3-way sync, `validate_schemas.py` | Missing: Type validation (mypy covers this) |

### SOP Automation Status

 | SOP Area | Current State | Tool | Automation Level |
|-----------|---------------|------|-----------------|
| **Development Setup** | ✅ Automated | `make install`, `moon run :dev` | 100% |
| **Code Quality** | ✅ Automated | Ruff pre-commit, mypy pre-commit, CI lint | 100% |
| **Testing** | ✅ Automated | `moon run :test`, pytest-xdist | 100% |
| **Debugging** | ✅ Automated | `tools/debug.py` (env auto-detect) | 100% |
| **Deployment** | ✅ Automated | `tools/dokploy_deploy.sh`, `moon run :deploy` | 100% |
| **Environment Consistency** | ✅ Automated | `tools/check_env_keys.py`, `validate_schemas.py` | 100% |
| **Container Management** | ✅ Automated | `cleanup_leaked_containers.py` | 100% |
| **PDF Fixture Generation** | 🟡 Semi-automated | `tools/_lib/pdf_fixtures/` with `tools/generate_pdf_fixtures.py` | 60% |
| **Smoke Testing** | ✅ Automated | `tools/smoke_test.sh` | 100% |

### Documentation Constraints Found

| File | MUST/REQUIRE | Status | Action Taken |
|------|---------------|--------|--------------|
| `AGENTS.md` | 5 instances | ✅ Removed | PR #242 |
| `docs/ssot/accounting.md` | 2 instances | ✅ Removed | PR #242 |
| `docs/ssot/development.md` | 3 instances | ✅ Removed | PR #242 |
| `docs/ssot/extraction.md` | 1 instance | ✅ Removed | PR #242 |
| `docs/ssot/schema.md` | 1 instance | ✅ Removed | PR #242 |
| **Total** | **12 instances** | **Phase 1 Complete** | |

### Runtime Constraints Analysis

**Result: NO runtime constraints to remove.**

The codebase correctly separates concerns:
- ✅ Test assertions → only in test files (proper use)
- ✅ Pydantic validators → API boundary validation (proper use)
- ✅ Domain exceptions → Business logic enforcement (legitimate, cannot be static)
- ✅ No `assert()` in production code
- ✅ No blocking validation decorators beyond Pydantic

All existing runtime constraints are **legitimate business logic** (e.g., journal entry must balance) that **cannot** be replaced with static analysis.

---

## 🎯 Transformation Roadmap

### Phase 1: Documentation Cleanup ✅ (COMPLETE)

**Goal**: Remove all MUST/REQUIRE statements from documentation.

**Completed** (PR #242):
- ✅ Removed `MUST` formatting from AGENTS.md
- ✅ Changed "REQUIRED for contributors" to "Recommended"
- ✅ Replaced constraint prose with test references
- ✅ Updated 5 SSOT documents with test links

**Evidence**:
- Before: `**MUST** use Decimal for monetary amounts`
- After: `See: apps/backend/tests/accounting/test_decimal_safety.py`

---

### Phase 2: Tooling Gap Analysis (Historical Snapshot)

**Goal**: Identify SOPs that lack automation and create tooling plan.

#### 2.1 Missing Pre-commit Hooks

| Gap | Impact | Priority | Solution |
|------|--------|----------|----------|
| **No mypy/type checking** | Type errors slip into CI | P0 | Add `mypy` to pre-commit |
| **No schema validation** | Invalid config types accepted | P0 | Add Pydantic model validation hook |
| **No migration length check** | Long filenames cause issues | P0 | Already exists (test_schema_guardrails) |
| **No dependency security scan** | Vulnerable deps allowed | P1 | Add `safety` or `pip-audit` hook |
| **No dockerfile lint** | Inconsistent images | P1 | Add `hadolint` hook |

#### 2.2 Missing CI Checks

| Gap | Impact | Priority | Solution |
|------|--------|----------|----------|
| **No E2E tests in main CI** | Integration failures slip | P0 | Integrate smoke_test.sh into pr-test.yml |
| **No performance regression** | Slow deploys go unnoticed | P1 | Add benchmark tests |
| **No dependency freshness** | Outdated packages | P1 | Add `pip outdated` check |
| **No API contract tests** | Breaking changes in PRs | P2 | Add OpenAPI validation |

#### 2.3 SOPs Needing Automation

| SOP | Current State | Target State | Tool Priority |
|-----|---------------|---------------|---------------|
| **Container cleanup** | Manual script | Auto-cleanup on exit | P1 |
| **PDF fixture generation** | Interactive | CLI with templates | P1 |
| **Secret rotation** | Manual + docs | Auto-detect & alert | P0 |
| **Config validation** | Runtime only | Pre-commit check | P0 |

---

### Phase 3: Tooling Implementation

**Goal**: Implement missing tools to close gaps identified in Phase 2.

#### 3.1 Pre-commit Enhancements

```yaml
# .pre-commit-config.yaml additions

# Type checking
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: v1.10.0
  hooks:
    - id: mypy
      additional_dependencies:
        - pydantic
        - sqlalchemy
      args: [--strict]

# Security scanning
- repo: https://github.com/Lucas-C/pre-commit-hooks-safety
  rev: v1.3.4
  hooks:
    - id: python-safety-dependencies-check
      files: requirements.txt

# Dockerfile linting
- repo: https://github.com/hadolint/hadolint
  rev: v2.12.0
  hooks:
    - id: hadolint-docker
      files: ^apps/.*Dockerfile$

# Schema validation (local hook)
- repo: local
  hooks:
    - id: validate-config-schemas
      name: Validate Pydantic schemas
      entry: python tools/validate_schemas.py
      language: python
      files: ^(apps/backend/src/config\.py|apps/backend/src/schemas/.*\.py)$
```

#### 3.2 Tool Enhancements

**New Tool: `tools/validate_schemas.py`**
```python
#!/usr/bin/env python3
"""
Validate Pydantic models in config and schemas.

Ensures:
1. All config fields have default values or validation
2. All schema fields have documentation (Field(description=...))
3. No required fields without defaults in Settings
"""

# Implementation would validate Pydantic models at static time
```

**Enhanced: `tools/debug.py`**
- Add `--auto-cleanup` flag to remove leaked containers after debugging
- Add `--health-check` to run basic smoke tests

**Enhanced: `tools/generate_pdf_fixtures.py`**
- Add `--template bank=dbs|cmb|moomoo|pingan|mari` flag
- Add `--auto-verify` to run validation after generation
- Add `--export-json` for non-interactive use

#### 3.3 CI Enhancements

**Add to `.github/workflows/ci.yml`**:
```yaml
# New job: E2E Tests
e2e:
  name: E2E Smoke Tests
  needs: [backend, frontend]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        submodules: recursive
    - name: Install moon
      uses: moonrepo/setup-toolchain@v0
    - name: Run smoke tests
      run: bash tools/smoke_test.sh local
```

**Add to `.github/workflows/pr-test.yml`**:
```yaml
# Add dependency freshness check
dependency-check:
  name: Check for outdated dependencies
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Check outdated
      run: uv pip list --outdated
```

---

### Phase 4: SOP Documentation Standardization

**Goal**: Ensure every SOP follows the same structure and has tooling backing.

#### 4.1 SOP Template

Every SOP document should follow this structure:

```markdown
# SOP: [Operation Name]

> **Purpose**: [One sentence explaining why this SOP exists]
> **Automated**: ✅ [Tool Name] | 🟡 [Partial] | ❌ [Manual - TODO]

## Background
[Context: What problem does this solve? Why is it important?]

## Prerequisites
[What you need before starting]

## Automated Tool
```bash
# Primary command
[tool-command] [args]

# Examples with flags
[tool-command] --help
```

**What it does**:
- [ ] [Check 1]
- [ ] [Check 2]
- [ ] [Check 3]

**Failure modes**:
- Error A → [How to fix]
- Error B → [How to fix]

## Manual Fallback (if tool unavailable)
[Step-by-step guide for rare cases]

## Related Tests
- `tests/[test-file]` - [What it validates]
- CI check: `[workflow-name]` - [When it runs]

## References
- SSOT: `[doc-name].md`
- Issue: `#XXX`
```

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../../AGENTS.md](../../AGENTS.md) — repository-wide agent and contributor entry point.
- [./AUDITS.md](./AUDITS.md) — audit index and retired standalone report notes.
- [./AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) — historical consistency audit snapshot.
- [./DECISIONS.md](./DECISIONS.md) — project decision log.
- [./DECISIONS_ZH.md](./DECISIONS_ZH.md) — Chinese mirror of project decision notes.
- [../ssot/tdd.md](../ssot/tdd.md) — canonical EPIC -> AC -> test workflow.
- [../agents/orchestration.md](../agents/orchestration.md) — agent workflow governance.
- [../agents/red-lines.md](../agents/red-lines.md) — security and engineering hard stops.
- [../contributing/branch-policy.md](../contributing/branch-policy.md) — branch and PR workflow.
- [../../.github/copilot-instructions.md](../../.github/copilot-instructions.md) — Copilot-specific contributor instructions.
- [../../.github/instructions/frontend.instructions.md](../../.github/instructions/frontend.instructions.md) — frontend assistant instructions.
- [../../.github/instructions/python.instructions.md](../../.github/instructions/python.instructions.md) — Python assistant instructions.
- [../../.github/pull_request_template.md](../../.github/pull_request_template.md) — PR description contract.
- [../../apps/backend/tests/README.md](../../apps/backend/tests/README.md) — test-suite organization, jointly owned with EPIC-008.

#### 4.2 SOP Inventory & Gap Analysis

| SOP Area | Current Doc | Tool | Gap |
|----------|-------------|------|-----|
| **Development Setup** | README.md | `make install` | ✅ Complete |
| **Code Quality** | development.md | Ruff, pre-commit | ✅ Complete |
| **Testing** | tests/README.md | `moon run :test` | ✅ Complete |
| **Debugging** | development.md | `debug.py` | ✅ Complete |
| **Deployment** | EPIC-007 | `dokploy_deploy.sh` | ✅ Complete |
| **Env Consistency** | development.md | `check_env_keys.py` | ✅ Complete |
| **Secret Rotation** | (missing) | (missing) | ❌ Gap |
| **Container Cleanup** | (missing) | `cleanup_leaked_containers.py` | 🟡 No doc |
| **PDF Fixtures** | EPIC-009 | `generate_pdf_fixtures.py` | 🟡 Semi-auto |
| **Smoke Tests** | EPIC-008 | `smoke_test.sh` | ✅ Complete |

**Gaps to fill**:
1. ✅ Container cleanup documentation (100% - documented in EPIC-014)
2. 🟡 Secret rotation SOP + tool (HIGH priority)
3. 🟡 PDF fixture generation fully automated (MEDIUM priority)

**Notes on P0 Completion**:
- ✅ validate_schemas.py found 16 fields lacking Field() descriptions (warnings, not errors)
- ✅ mypy hook added with --warn-unused-ignores for gradual adoption (123 existing type errors will be addressed over time)
- ✅ All P0 requirements satisfied: documentation is descriptive, not prescriptive
- ✅ All SOPs have automated tool backing
- ✅ Pre-commit hooks enforce static constraints (mypy + validate_schemas)
- ✅ CI pipeline enforces runtime constraints (smoke_test.sh integrated in pr-test.yml)

#### 4.3 Archive Integration Notes

The project archive has been swept, removed from the repository, and indexed in
[#548](https://github.com/wangzitian0/finance_report/issues/548). Its useful
operating-model content is owned by active EPICs:

- Historical AC audit inventories are now lineage only; current metrics come
  from generated registries and the AC coverage report.
- QA standardization guardrails are owned by EPIC-012, SSOT docs, and tests
  instead of standalone archive reports.
- Testing implementation and coverage plans are owned by EPIC-008 plus the
  generated coverage policy/report.
- EPIC-specific implementation and gap notes were folded into EPIC-002,
  EPIC-004, EPIC-011, EPIC-012, and EPIC-013.
- Future documentation/code/test conversion work is tracked by issues #453,
  #454, #455, and #456 instead of prose-only TODOs.

---

### Phase 5: Documentation Evolution

**Goal**: Transform documentation from prescriptive to descriptive.

#### 5.1 Documentation Hierarchy

| Layer | Responsibility | Examples | Enforced By |
|--------|---------------|-----------|-------------|
| **1. SSOT** | Design decisions, data models | `schema.md`, `accounting.md` | Tests (test_decimal_safety.py) |
| **2. Guidelines** | Best practices, patterns | `development.md`, `extraction.md` | Pre-commit hooks, CI |
| **3. SOPs** | Operational procedures | `debug.py`, deployment guides | Automated tools |
| **4. READMEs** | Getting started, directory intros | `README.md`, `apps/*/README.md` | N/A (user-facing) |

#### 5.2 Writing Guidelines

**DO** (Descriptive):
- ✅ "Use Decimal for monetary amounts to avoid precision errors. See: test_decimal_safety.py"
- ✅ "Enum columns require explicit names to prevent migration conflicts. See: test_schema_guardrails.py::test_enums_have_explicit_names"
- ✅ "Environment variables must be consistent across secrets.ctmpl, config.py, and .env.example. Run `make env-check` to verify."

**DON'T** (Prescriptive):
- ❌ "You MUST use Decimal for all monetary amounts."
- ❌ "REQUIRE: All Enum columns MUST have a name parameter."
- ❌ "PRE-COMMIT HOOKS (REQUIRED for contributors)"

**Why**: Prescriptive statements create documentation drift. If the constraint changes, you must update docs + tests. With test references, tests are truth, docs are guidance.

#### 5.3 Documentation Quality Checklist

Before marking a doc as "Complete", verify:

- [ ] No `MUST`, `REQUIRE`, `NEVER` in prescriptive context
- [ ] Every constraint has a test reference
- [ ] Every SOP has an automated tool backing it
- [ ] "Why this matters" sections explain the rationale
- [ ] Examples use the automated tool, not manual steps
- [ ] Related tests are linked by path and test name

---

## 🛠️ Implementation Tasks

### Phase 1 Tasks ✅ (COMPLETE)
- [x] Remove MUST/REQUIRE from AGENTS.md
- [x] Update SSOT docs with test references
- [x] Soften "REQUIRED for contributors" to "Recommended"
- [x] PR #242 created and merged

### Phase 2 Tasks ✅ (COMPLETE)
- [x] Add mypy pre-commit hook
- [x] Create `tools/validate_schemas.py`
- [x] Add dependency security scan (safety/pip-audit)
- [ ] Add hadolint for Dockerfile linting (P1)
- [x] Integrate smoke_test.sh into pr-test.yml
- [x] Document container cleanup SOP
- [x] Assess secret rotation needs

### Phase 3 Tasks (PLANNED)
- [ ] Implement all pre-commit enhancements
- [ ] Enhance debug.py with auto-cleanup
- [ ] Enhance pdf_fixtures with CLI flags
- [ ] Add E2E tests to main CI
- [ ] Add dependency freshness check to CI

### Phase 4 Tasks (PLANNED)
- [ ] Create SOP template document
- [ ] Audit all SOPs for tooling backing
- [ ] Create secret rotation SOP + tool
- [ ] Standardize PDF fixture generation CLI

### Phase 5 Tasks (PLANNED)
- [ ] Document new writing guidelines
- [ ] Create documentation quality checklist
- [ ] Audit all docs for compliance
- [ ] Train team on new guidelines

---

## 📊 Success Metrics Snapshot

The values below are historical progress markers for this EPIC. Current metrics
should be regenerated from tooling or read from CI artifacts.

### Quantitative

| Metric | Snapshot | Target | Status |
|--------|----------|--------|--------|
| **MUST/REQUIRE instances in docs** | 0 | 0 | ✅ Done |
| **SOPs with automated tools** | 10/10 (100%) | 10/10 (100%) | ✅ Done |
| **Pre-commit hook coverage** | 95% | 95% | ✅ Done |
| **CI runtime checks** | 5 major | 5 major | ✅ Done |
| **Documentation-test alignment** | 100% | 100% | ✅ Done |

### Qualitative

- [ ] New developers can follow SOPs without asking "is this still current?"
- [ ] CI catches all constraint violations before merge
- [ ] Documentation explains "why" not just "what"
- [ ] No manual checklist processes remain
- [ ] PR reviews focus on design, not style/constraints

---

## 🔗 Related Documents

- **AGENTS.md** - Agent behavioral guidelines (now TTD-aligned)
- **docs/ssot/development.md** - Development workflow and environment
- **docs/ssot/schema.md** - Database schema constraints (test-backed)
- **docs/project/README.md** - EPIC tracking
- **EPIC-008** - Testing strategy (E2E integration)
- **EPIC-012** - Foundation libraries (tooling enhancements)

---

## ❓ Open Questions

1. **Secret Rotation Scope**: Should we build auto-rotation or just detection/alerting?
   - *Discussion*: Vault has native rotation. Integration complexity vs. value.
   - *Proposal*: Start with detection (check token expiry in `debug.py`), add rotation in EPIC-015.

2. **PDF Fixture Automation Level**: Full CLI vs. Interactive generator?
   - *Current*: Semi-interactive (select bank, confirm)
   - *Proposal*: Add `--batch` mode for CI, keep interactive for local dev.

3. **Type Checking Strictness**: mypy `--strict` vs. `--warn-unused-ignores`?
   - *Proposal*: Start with `--warn-unused-ignores`, migrate to `--strict` over 2 sprints.

---

## 📅 Historical Planning Timeline

This table is a planning snapshot, not a live delivery schedule.

| Phase | Duration | Target Completion | Status |
|-------|----------|------------------|--------|
| **Phase 1: Doc Cleanup** | 3 days | ✅ Jan 29, 2026 | Complete |
| **Phase 2: Gap Analysis** | 5 days | ✅ Jan 30, 2026 | Complete |
| **Phase 3: Tooling** | 10 days | Feb 15, 2026 | Planned |
| **Phase 4: SOP Standardization** | 7 days | Feb 22, 2026 | Planned |
| **Phase 5: Documentation Evolution** | 5 days | Feb 27, 2026 | Planned |

**Total Duration**: 4-5 weeks

---

## Historical Notes

Historical work-progress reports and test-organization audits were removed from this EPIC. Current TTD scope is defined by the objective, SSOT links, and the AC table below; live proof is owned by generated registries and executable checks.

---

## 🧪 Infra Test Cases (Coverage Enforcement)

> **Registry**: `docs/infra_registry.yaml`
> **Coverage**: See `apps/backend/tests/infra/`

### AC14.1: Coverage Enforcement Tooling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC14.1.1 | Backend coverage ≥ 90% enforced locally via `pyproject.toml` (CI uses `--cov-fail-under=0`; target: 99%; local pre-push enforcement threshold: 90%) | `test_coverage_threshold_enforced` | `infra/test_coverage_enforcement.py` | P0 |
| AC14.1.2 | Pre-commit mypy hook blocks type errors before commit | `test_mypy_precommit_blocks_type_errors` | `infra/test_precommit_hooks.py` | P0 |
| AC14.1.3 | validate_schemas.py exits non-zero when Pydantic fields lack Field() descriptions | `test_validate_schemas_fails_missing_desc` | `infra/test_validate_schemas.py` | P0 |
| AC14.1.4 | check_env_keys.py detects missing keys across secrets.ctmpl, config.py, .env.example | `test_env_keys_three_way_sync` | `infra/test_check_env_keys.py` | P0 |
| AC14.1.5 | smoke_test.sh runs successfully against local docker environment | `test_smoke_test_local_pass` | `infra/test_smoke_test.py` | P1 |
| AC14.1.6 | generate_ac_registry.py produces zero ghost ACs and zero overlap between feature and infra registries | `test_ac_registry_no_ghost_no_overlap` | `tests/tooling/test_issue_493_foundation_ttd_behavior.py` | P1 |
