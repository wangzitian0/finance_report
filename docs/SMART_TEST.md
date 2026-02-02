# 🚀 Smart Testing Strategy: Fast + High Quality

## Core Principle

> **Run coverage (99%) only for changed files, run the full test suite without coverage**

✅ **Fast**: Full test suite runs without coverage overhead (estimated 60–70% faster)  
✅ **Strict**: Changed code must reach 99% coverage  
✅ **Safe**: All tests are executed to ensure existing behavior is not broken

---

## How to Use

### 🎯 Recommended: Smart Tests (day-to-day development)

```bash
moon run backend:test-smart
```

**How it works**:
1. Detects Git-changed Python files
2. If changes exist:
   - ✅ Run **all tests** (fast, no coverage)
   - ✅ Collect coverage only on **changed files** (requires 99%)
3. If no changes:
   - Fall back to full coverage testing (94%)

### ⚡ Ultra-Fast Mode: Skip all coverage

```bash
moon run backend:test-no-cov
```

**Use cases**:
- Quick test validation
- TDD red-green refactoring loop
- Estimated **60-70% speedup**

### 📊 Full Mode: All file coverage

```bash
moon run backend:test-execution
```

**Use cases**:
- CI pipeline
- Pre-commit final check
- Post-refactoring validation

---

## 📈 Performance Comparison

| Mode | Command | Execution Time | Coverage Check | Use Case |
|------|---------|----------------|----------------|----------|
| **Smart Mode** | `test-smart` | **~40%** ⚡ | Changed files 99% | **Daily development (Recommended)** |
| Ultra-Fast Mode | `test-no-cov` | **~30%** 🚀 | None | Quick validation |
| Fast Mode | `test-execution-fast` | ~65% | All 94% | Pre-commit check |
| Full Mode | `test-execution` | 100% | All 94% | CI pipeline |

---

## 🔍 How It Works

### Change Detection Logic

The script `scripts/get_changed_files.py` detects changes by priority:

1. **Branch diff**: `git diff main...HEAD` - Current branch vs main
2. **Uncommitted changes**: `git diff HEAD` - Working directory changes
3. **Staged changes**: `git diff --cached` - Files added with git add

### Coverage Calculation

```bash
# Assume you modified src/services/reconciliation.py

# Smart mode only checks this file's coverage:
pytest --cov=src.services.reconciliation \
       --cov-fail-under=99 \
       -n auto \
       tests/  # But runs all tests!
```

**Key advantages**:
- All 912 tests execute (ensures no functionality is broken)
- Only collects coverage on changed files (saves 60% time)
- Higher bar for changed code (99% vs 94%)

---

## 🎓 Usage Examples

### Scenario 1: Adding new feature

```bash
# 1. Modify src/services/reconciliation.py
# 2. Run smart tests
moon run backend:test-smart

# Sample output:
# 📊 Test Plan:
#   ├─ Changed modules: 1
#   ├─ Coverage target: Only changed files (99%)
#   └─ Test scope: All tests (fast, no coverage overhead)
#
# ⚡ Smart mode: Full tests + Coverage on changed files only
#   • src.services.reconciliation
#
# ========== 912 passed in 45s ==========
# Coverage: src/services/reconciliation.py: 99%
```

### Scenario 2: Refactoring existing code

```bash
# 1. Refactor src/models/account.py and src/services/accounting.py
# 2. Run smart tests
moon run backend:test-smart

# Sample output:
# ⚡ Smart mode: Full tests + Coverage on changed files only
#   • src.models.account
#   • src.services.accounting
#
# Coverage:
#   src/models/account.py: 100%
#   src/services/accounting.py: 98%
```

### Scenario 3: Config file changes (no code changes)

```bash
# 1. Modify pyproject.toml
# 2. Run smart tests
moon run backend:test-smart

# Sample output:
# ✅ No source changes detected - running full coverage
# ========== 912 passed in 120s ==========
# Coverage: 94.2%
```

---

## 🛡️ Quality Assurance

### Why doesn't this strategy reduce quality?

1. **All tests execute** ✅
   - Regardless of coverage configuration, all 912 tests run
   - Changes don't break existing functionality

2. **Stricter for new code** ✅
   - Changed files require **99%** coverage (vs original 94%)
   - Ensures new features have adequate testing

3. **Regression protection** ✅
   - Full test suite ensures no unexpected breakage
   - Test failures still reported even when skipping coverage collection

---

## 🔧 Manual Control

### Force check specific module coverage

```bash
cd apps/backend
uv run pytest -n auto \
    --cov=src.services.reconciliation \
    --cov=src.services.accounting \
    --cov-fail-under=99 \
    --cov-report=term-missing
```

### View current changes

```bash
python scripts/get_changed_files.py --format list
```

### View coverage parameters

```bash
python scripts/get_changed_files.py --format pytest
```

---

## 📦 File Inventory

```
scripts/
├── get_changed_files.py    # Git change detection script
├── smart_test.py           # Smart test orchestration script
└── fast_test.py            # Ultra-fast test (no coverage)

apps/backend/moon.yml
├── test-smart              # Smart mode (recommended)
├── test-no-cov             # Ultra-fast mode
├── test-execution-fast     # Fast mode
└── test-execution          # Full mode (CI)
```

---

## 🎯 Best Practices

### Daily Development Loop

```bash
# 1. TDD red-green cycle (fastest)
moon run backend:test-no-cov

# 2. Verify coverage after feature completion
moon run backend:test-smart

# 3. Final pre-commit check (optional)
moon run backend:test-execution-fast
```

### CI Pipeline

```bash
# Keep using full mode
moon run backend:test-execution
```

### Large-scale Refactoring

```bash
# Option 1: Smart mode (recommended)
moon run backend:test-smart

# Option 2: Manually specify key modules
cd apps/backend
uv run pytest -n auto \
    --cov=src.services \
    --cov=src.models \
    --cov-fail-under=95
```

---

## ⚠️ Notes

### Coverage 99% too strict?

You can adjust the threshold in `scripts/smart_test.py`:

```python
# Line 66, change to 95%
"--cov-fail-under=95",
```

### Changes not detected?

Ensure your branch is based on `main`:

```bash
git fetch origin
git rebase origin/main
```

Or manually specify base branch:

```bash
python scripts/get_changed_files.py --base develop
```

---

## 🚀 Quick Start

```bash
# Try smart testing!
moon run backend:test-smart
```

First run with no changes will automatically fall back to full coverage.  
After modifying any file under `apps/backend/src/`, run again to experience smart mode speed!
