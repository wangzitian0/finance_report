# Quick Command Reference

## Immediate Actions (Copy-Paste Ready)

### 1. Push the Branch
```bash
git push origin perf/ci-speedup
```

### 2. Create Pull Request (GitHub CLI)
```bash
gh pr create --title "perf: enable parallel test execution with pytest-xdist" \
  --body-file .sisyphus/notepads/ci-optimization/PR_TEMPLATE.md \
  --base main
```

**Or manually**: Copy contents of `PR_TEMPLATE.md` to GitHub PR form.

### 3. Monitor CI Status
```bash
# Watch CI status
gh pr view --web

# Or check directly
open https://github.com/wangzitian0/finance_report/actions
```

---

## Local Verification Commands (Already Passed)

```bash
# Run parallel tests (what we optimized)
moon run backend:test-execution

# Run full CI suite locally
moon run :ci

# Lint check
moon run :lint

# Manual parallel test with specific worker count
cd apps/backend && uv run pytest -n 4 tests/ -v
```

---

## Post-Merge Verification

### Check CI Timing
```bash
# After merge, run CI and time it
time moon run :ci
```

**Expected**: ~6-7 minutes total (vs 12-14 min before)

### Verify Staging Deploy
After next push to main, check staging deploy workflow timing:
- Expected: 5-7 minutes faster (removed redundant CI step)

---

## Troubleshooting (If CI Fails)

### View CI Logs
```bash
# Get latest CI run
gh run list --limit 1

# View logs for specific run
gh run view <run-id> --log
```

### Common Issues & Fixes

**Issue 1: Coverage collection fails in CI**
```bash
# Workaround: Disable coverage with xdist temporarily
# Edit apps/backend/moon.yml, add --no-cov flag
```

**Issue 2: Worker count too high for CI runner**
```bash
# Change -n auto to explicit count
# apps/backend/moon.yml: replace "-n auto" with "-n 4"
```

**Issue 3: Database connection issues**
```bash
# Verify DATABASE_URL in CI environment
# Check .github/workflows/ci.yml postgres service config
```

### Rollback (If Needed)
```bash
# If CI fails and needs immediate rollback
git revert 7dfc6db
git push origin perf/ci-speedup
```

---

## Performance Baseline

**Before This PR**:
- Backend tests: 427s (7 min)
- Staging deploy: +5-7 min redundant CI
- Total CI: ~12-14 min

**After This PR** (Expected):
- Backend tests: ~75s (1.5 min in CI, accounting for CI overhead)
- Staging deploy: Direct to build
- Total CI: ~6-7 min

**Target**: < 4 minutes for backend tests in CI

---

## Documentation Locations

| Document | Purpose |
|----------|---------|
| `PR_TEMPLATE.md` | Ready-to-use PR description |
| `FINAL_STATUS.md` | Executive summary of changes |
| `SUMMARY.md` | Performance metrics & verification |
| `learnings.md` | Implementation patterns |
| `decisions.md` | Architectural choices |
| `issues.md` | Problems & solutions |
| `problems.md` | Blocker documentation |

---

**Current Status**: ✅ All code complete, ready to push
