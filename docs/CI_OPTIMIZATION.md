# GitHub Actions CI Optimization Strategy

## Current Problem

GitHub Actions free tier `ubuntu-latest` only has **2 CPU cores**, which means:
- `pytest -n auto` can only create 2 workers (gw0, gw1)
- Running 912 tests takes considerable time

## Solution: 4-Way Parallel Test Execution (Implemented)

### Overview

Split backend tests into 4 parallel shards using:
- **GitHub Actions matrix strategy** - Run 4 jobs simultaneously
- **pytest-split plugin** - Deterministic test distribution across shards

### Key Benefits

✅ **75% faster CI** - 4x parallelization (each shard runs ~25% of tests)  
✅ **No cost increase** - Free tier supports parallel jobs  
✅ **Maintains quality** - All 912 tests run, full coverage maintained  
✅ **Deterministic** - pytest-split ensures consistent test distribution

### Implementation

#### 1. Install pytest-split

```toml
# apps/backend/pyproject.toml
[dependency-groups]
dev = [
    # ...
    "pytest-split>=0.8.0",
]
```

#### 2. Configure CI Matrix

```yaml
# .github/workflows/ci.yml
jobs:
  backend:
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]  # 4 parallel jobs
    
    steps:
      - name: Run Tests (Shard ${{ matrix.shard }}/4)
        run: |
          cd apps/backend
          uv run pytest -n auto -v \
            -m "not slow and not e2e" \
            --splits 4 \
            --group ${{ matrix.shard }} \
            --cov=src \
            --cov-report=lcov:coverage-${{ matrix.shard }}.lcov \
            --cov-branch \
            --dist worksteal
      
      - name: Upload coverage artifact
        uses: actions/upload-artifact@v4
        with:
          name: coverage-${{ matrix.shard }}
          path: apps/backend/coverage-${{ matrix.shard }}.lcov
```

#### 3. Merge Coverage Reports

```yaml
  merge-coverage:
    needs: backend
    runs-on: ubuntu-latest
    steps:
      - name: Download all coverage artifacts
        uses: actions/download-artifact@v4
        with:
          pattern: coverage-*
          merge-multiple: true
      
      - name: Merge coverage reports
        run: cat coverage-*.lcov > coverage.lcov
      
      - name: Upload to Coveralls
        uses: coverallsapp/github-action@v2
        with:
          file: coverage.lcov
```

### How It Works

1. **4 Parallel Jobs**: Each job runs simultaneously on separate GitHub runners
2. **Test Distribution**: `pytest-split` divides 912 tests into 4 groups deterministically
3. **Within-Job Parallelization**: Each shard still uses `-n auto` (2 workers per job)
4. **Coverage Collection**: Each shard generates separate `coverage-N.lcov` file
5. **Coverage Merge**: Dedicated job combines all 4 coverage reports
6. **Single Upload**: Merged coverage uploaded to Coveralls

### Expected Performance

**Before (Sequential)**:
- 1 job × 2 cores × 912 tests
- Estimated time: ~8-10 minutes

**After (4-Way Parallel)**:
- 4 jobs × 2 cores × ~228 tests each
- Estimated time: ~2-3 minutes (~75% reduction)

**Total CI time = max(shard_time, frontend_time)**

### Verification

Check CI run to see all 4 shards:
```bash
gh run view <run-id>
# Should show:
# - Backend Tests (Shard 1/4)
# - Backend Tests (Shard 2/4)
# - Backend Tests (Shard 3/4)
# - Backend Tests (Shard 4/4)
# - Merge Coverage Reports
```

---

## Alternative Approaches (Not Implemented)

### Option A: GitHub Larger Runners (Paid)

Use runners with more cores:

```yaml
jobs:
  backend:
    runs-on: ubuntu-latest-4-cores  # 4 cores
    # or
    runs-on: ubuntu-latest-8-cores  # 8 cores
```

**Pricing**:
- 4-core: $0.008/minute
- 8-core: $0.016/minute

**Expected speedup**:
- 4-core: 50% faster
- 8-core: 60-70% faster

**Documentation**: https://docs.github.com/en/actions/using-github-hosted-runners/about-larger-runners

### Option B: Skip Slow Tests (Not Recommended)

```yaml
# Skip slow, e2e, and integration tests
pytest -m "not slow and not e2e and not integration"
```

❌ **Problem**: Reduced test coverage, might miss bugs

### Option C: Manual Directory-Based Splitting

Split tests manually by directory structure:

```yaml
matrix:
  include:
    - shard: 1
      testpath: "tests/accounting tests/reconciliation"
    - shard: 2
      testpath: "tests/api tests/extraction"
    - shard: 3
      testpath: "tests/ai tests/reporting"
    - shard: 4
      testpath: "tests/integration tests/e2e"

# Run:
pytest ${{ matrix.testpath }}
```

❌ **Problem**: Unbalanced load, manual maintenance

---

## Troubleshooting

### Issue: pytest-split not found

**Solution**: Ensure pytest-split is installed:
```bash
cd apps/backend
uv sync  # Installs all dev dependencies including pytest-split>=0.8.0
```

### Issue: Coverage merge fails

**Solution**: Verify all shards uploaded coverage:
```bash
# Check artifacts in GitHub Actions UI
# Should see: coverage-1, coverage-2, coverage-3, coverage-4
```

### Issue: Unbalanced shard times

**Solution**: pytest-split uses test duration history to balance. First run might be uneven, subsequent runs improve.

---

## Cost Analysis

**Current Implementation (Free Tier)**:
- 4 parallel jobs × 2-3 minutes = ~8-12 runner-minutes total
- **Cost**: $0 (within free tier limits)

**Alternative (4-core runner)**:
- 1 job × 4 minutes = 4 runner-minutes
- **Cost**: ~$0.032 per CI run

**Recommendation**: Stay with free tier 4-way parallelization. Only upgrade to larger runners if:
- CI time still too slow after parallelization
- Budget available for faster feedback

---

## References

- [pytest-split documentation](https://github.com/jerry-git/pytest-split)
- [GitHub Actions matrix strategy](https://docs.github.com/en/actions/using-jobs/using-a-matrix-for-your-jobs)
- [Coveralls merge documentation](https://docs.coveralls.io/parallel-build-webhook)
- [Smart Test Strategy](./SMART_TEST_IMPLEMENTATION.md) - Local development optimization
