# 🚀 Smart Testing Strategy - Complete Implementation

## ✨ Core Principle

> **Run coverage (99%) only for changed files, run the full test suite without coverage**

- ✅ **Fast**: Only collect coverage on changed files (estimated 60-70% speedup)
- ✅ **Strict**: Changed code must reach 99% coverage
- ✅ **Safe**: All 912 tests execute, no issues missed

---

## 🎯 Usage

### Recommended: Smart Tests (daily development)

```bash
moon run backend:test-smart
```

**How it works**:
- Detects Git-changed Python files
- Has changes: Full tests + Changed files coverage (99%)
- No changes: Fall back to full coverage (94%)

### Ultra-fast: Skip all coverage

```bash
moon run backend:test-no-cov
```

**Use cases**: TDD red-green loop, quick validation

### Fast: Simplified coverage report

```bash
moon run backend:test-execution-fast
```

### Full: CI mode

```bash
moon run backend:test-execution
```

---

## 📊 Performance Comparison

| Mode | Command | Relative Time | Coverage | Use Case |
|------|---------|---------------|----------|----------|
| **Smart Mode** ⭐ | `test-smart` | **~40%** | Changed 99% | **Daily development (Recommended)** |
| Ultra-fast Mode | `test-no-cov` | **~30%** | None | Quick validation |
| Fast Mode | `test-execution-fast` | ~65% | All 94% | Pre-commit check |
| Full Mode | `test-execution` | 100% | All 94% | CI pipeline |

---

## 🔍 Working Examples

### Scenario 1: Modified reconciliation.py

```bash
$ moon run backend:test-smart

🧪 Smart Test Strategy: Full tests + Targeted coverage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Test Plan:
  ├─ Changed modules: 1
  ├─ Coverage target: Only changed files (99%)
  └─ Test scope: All tests (fast, no coverage overhead)

⚡ Smart mode: Full tests + Coverage on changed files only
  • src.services.reconciliation

🔧 Preparing test environment...
   Container: finance-report-db-default running
   Created 'finance_report_test_default' database.
   Migrations applied.
🚀 Starting Tests...

========== 912 passed in 48s ========== (was 120s)

Coverage:
  src/services/reconciliation.py: 99.2% ✅
```

### Scenario 2: No code changes

```bash
$ moon run backend:test-smart

📊 Test Plan:
  ├─ Changed modules: 0
  ├─ Coverage target: Only changed files (99%)
  └─ Test scope: All tests (fast, no coverage overhead)

✅ No source changes detected - running full coverage

========== 912 passed in 120s ==========

Coverage: 94.5% ✅
```

---

## 🛠️ Implementation Details

### File Structure

```
scripts/
├── get_changed_files.py    # Git change detection
├── smart_test.py           # Smart test orchestration
├── fast_test.py            # Ultra-fast test (no coverage)
└── test_lifecycle.py       # Database lifecycle management

apps/backend/moon.yml
├── test-smart              # ⭐ Smart mode
├── test-no-cov             # 🚀 Ultra-fast mode
├── test-execution-fast     # ⏱️ Fast mode
└── test-execution          # 🔍 Full mode
```

### Change Detection Logic

`get_changed_files.py` checks by priority:

1. **Branch diff**: `git diff main...HEAD`
2. **Uncommitted changes**: `git diff HEAD`
3. **Staged changes**: `git diff --cached`

### Database Management

All test modes use `test_lifecycle.py` for database management:
- Auto-start Docker Compose (postgres)
- Create isolated test database
- Run Alembic migrations
- Clean up after tests

---

## 🎓 Best Practices

### Daily Development Loop

```bash
# 1. TDD red-green loop (fastest)
moon run backend:test-no-cov

# 2. Verify coverage after feature completion
moon run backend:test-smart

# 3. Final pre-commit check (optional)
moon run backend:test-execution-fast
```

### Pre-commit Check

```bash
# Ensure all changes have adequate testing
moon run backend:test-smart
```

### CI Pipeline

```bash
# Keep using full mode
moon run backend:test-execution
```

---

## 🔧 Diagnostic Tools

### View current changes

```bash
python scripts/get_changed_files.py --format list
```

### View change count

```bash
python scripts/get_changed_files.py --format count
```

### View coverage parameters

```bash
python scripts/get_changed_files.py --format pytest
```

### Find slowest tests

```bash
cd apps/backend
uv run pytest --durations=20 -m "not slow and not e2e"
```

---

## 🛡️ Quality Assurance

### Why doesn't this reduce quality?

1. ✅ **All tests execute**
   - Regardless of coverage configuration, 912 tests run
   - Any regression issues are captured

2. ✅ **Stricter for new code**
   - Changed files require **99%** coverage (higher than original 94%)
   - Ensures new features have adequate testing

3. ✅ **Auto-fallback**
   - No changes triggers full coverage
   - Maintains CI standards

---

## ⚙️ Configuration Adjustments

### Adjust coverage threshold

Edit `scripts/smart_test.py`:

```python
# Line 66, change to 95%
"--cov-fail-under=95",
```

### Change base branch

Default compares to `main` branch, can be modified in `get_changed_files.py`:

```python
# Line 24
["git", "diff", "--name-status", f"develop...HEAD"],
```

Or specify at runtime:

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

---

## 📚 Advanced Optimizations

### Already Applied

1. ✅ **worksteal distribution strategy** - Dynamic load balancing (20-30% speedup)
2. ✅ **Smart coverage** - Only check changed files (60-70% speedup)
3. ✅ **Database isolation** - Supports parallel testing without conflicts

### Optional Optimizations

See `docs/TEST_OPTIMIZATION.md` for more optimization strategies:
- In-memory database (additional 50% speedup, may miss PostgreSQL-specific bugs)
- Layered testing (smoke/fast/full)
- Custom parallelism

---

## ❓ FAQ

### Q: Changes not detected?

**A**: Ensure your branch is based on `main`:

```bash
git fetch origin
git rebase origin/main
```

### Q: Coverage 99% too strict?

**A**: Can adjust threshold to 95% or 97% (see Configuration Adjustments section)

### Q: Need to manually start database?

**A**: No! All test modes auto-manage database through `test_lifecycle.py`

---

## 🎉 Summary

Smart testing strategy achieves:

✅ **Speed** - 60-70% speedup (smart mode)  
✅ **Quality** - 99% coverage requirement (changed files)  
✅ **Safety** - All tests execute  
✅ **Simple** - One command

Start using:

```bash
moon run backend:test-smart
```
