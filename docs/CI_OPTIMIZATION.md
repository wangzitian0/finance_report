# GitHub Actions CI 加速方案

## 当前问题

GitHub Actions 免费版 `ubuntu-latest` 只有 **2 个 CPU 核心**，导致：
- `pytest -n auto` 只能创建 2 个 worker（gw0, gw1）
- 912 个测试需要较长时间运行

## 解决方案

### 方案 1：使用 GitHub Larger Runners（推荐，需付费）

GitHub 提供更大的 runner：

```yaml
# .github/workflows/ci.yml
jobs:
  backend:
    name: Backend Tests
    runs-on: ubuntu-latest-4-cores  # 4 核心
    # 或
    runs-on: ubuntu-latest-8-cores  # 8 核心
```

**费用**：
- 4-core: $0.008/分钟
- 8-core: $0.016/分钟

**预计效果**：
- 4 核：测试时间减少 50%
- 8 核：测试时间减少 60-70%

**文档**: https://docs.github.com/en/actions/using-github-hosted-runners/about-larger-runners

---

### 方案 2：优化测试策略（免费）

#### 2.1 跳过慢测试

```yaml
# .github/workflows/ci.yml
- name: Run CI Pipeline
  env:
    DATABASE_URL: postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test
  run: |
    cd apps/backend
    uv run pytest -n auto -v \
      -m "not slow and not e2e and not integration" \
      --cov=src \
      --cov-report=lcov \
      --cov-branch \
      --cov-fail-under=94 \
      --dist worksteal \
      --maxfail=10
```

**新增**：
- `not integration`: 跳过外部 API 调用测试
- `--maxfail=10`: 失败 10 个后停止（快速失败）

---

#### 2.2 并行运行 Backend 和 Frontend

当前是串行，可以改为并行：

```yaml
jobs:
  backend:
    name: Backend Tests
    runs-on: ubuntu-latest
    # ... backend 配置

  frontend:
    name: Frontend Build
    runs-on: ubuntu-latest
    # ... frontend 配置
    # 移除 needs: backend（让它们并行）

  finish:
    needs: [backend, frontend]  # 等待两者完成
    # ...
```

**效果**：总时间 = max(backend, frontend) 而不是 backend + frontend

---

#### 2.3 使用 Matrix 策略拆分测试

将测试分成多个 job 并行运行：

```yaml
jobs:
  backend:
    name: Backend Tests (Group ${{ matrix.group }})
    runs-on: ubuntu-latest
    strategy:
      matrix:
        group: [1, 2, 3, 4]  # 分成 4 组并行
    
    steps:
      # ... 之前的步骤
      
      - name: Run Tests
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test
        run: |
          cd apps/backend
          uv run pytest -n auto \
            --splits 4 \
            --group ${{ matrix.group }} \
            --cov=src \
            --cov-report=lcov \
            --cov-branch \
            --dist worksteal
```

需要安装 `pytest-split`：
```toml
[dependency-groups]
dev = [
    "pytest-split>=0.8.0",
]
```

**效果**：4 个 job 并行，总时间减少 75%

---

### 方案 3：自托管 Runner（免费但需自己维护）

使用你自己的服务器/机器作为 GitHub Actions runner：

```yaml
jobs:
  backend:
    name: Backend Tests
    runs-on: self-hosted  # 使用你的 14 核机器
```

**优势**：
- 使用你本地 14 核机器
- 完全免费
- 更快的网络和缓存

**劣势**：
- 需要维护 runner
- 安全性需要自己保证

**设置**：https://docs.github.com/en/actions/hosting-your-own-runners

---

### 方案 4：只在关键分支运行完整测试

```yaml
# .github/workflows/ci.yml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend:
    name: Backend Tests
    runs-on: ubuntu-latest
    steps:
      - name: Run Tests
        run: |
          if [ "${{ github.event_name }}" == "push" ] && [ "${{ github.ref }}" == "refs/heads/main" ]; then
            # main 分支：完整测试
            moon run backend:test-execution
          else
            # PR：快速测试
            moon run backend:test-smart
          fi
```

**效果**：PR 时使用智能测试（快），merge 后完整测试（慢但全面）

---

## 推荐组合

### 免费账户
1. ✅ 使用 Matrix 策略（方案 2.3）- **最有效**
2. ✅ Backend/Frontend 并行（方案 2.2）
3. ✅ 跳过慢测试标记（方案 2.1）

**预计提速**：60-70%

### 付费账户
1. ✅ 使用 4-core runner（方案 1）- **最简单**
2. ✅ Backend/Frontend 并行（方案 2.2）

**预计提速**：70-80%

---

## 快速实现：Matrix 并行测试

```yaml
# .github/workflows/ci.yml
jobs:
  backend:
    name: Backend Tests (Shard ${{ matrix.shard }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: finance_report_test_${{ matrix.shard }}
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Install moon
        uses: moonrepo/setup-toolchain@v0
        with:
          cache: true
      
      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          version: "0.5.14"
          enable-cache: true
      
      - name: Set up Python
        run: uv python install 3.12
      
      - name: Cache Python venv
        uses: actions/cache@v4
        with:
          path: apps/backend/.venv
          key: venv-${{ runner.os }}-${{ hashFiles('apps/backend/uv.lock') }}
      
      - name: Install dependencies
        run: cd apps/backend && uv sync
      
      - name: Run Tests (Shard ${{ matrix.shard }}/4)
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test_${{ matrix.shard }}
        run: |
          cd apps/backend
          uv run pytest -n auto \
            --shard-id=${{ matrix.shard }} \
            --num-shards=4 \
            --cov=src \
            --cov-report=lcov:coverage-${{ matrix.shard }}.lcov \
            --cov-branch \
            -m "not slow and not e2e" \
            --dist worksteal
      
      - name: Upload coverage
        uses: actions/upload-artifact@v3
        with:
          name: coverage-${{ matrix.shard }}
          path: apps/backend/coverage-${{ matrix.shard }}.lcov

  merge-coverage:
    name: Merge Coverage
    needs: backend
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v3
      
      - name: Merge coverage reports
        run: |
          # 合并所有覆盖率报告
          cat coverage-*/coverage-*.lcov > coverage.lcov
      
      - name: Upload to Coveralls
        uses: coverallsapp/github-action@v2
        with:
          file: coverage.lcov
```

---

## 当前配置

你的 CI 已经用了 `worksteal`（最优分发策略），但受限于 2 核。

**立即可用的最佳方案**：实现 Matrix 并行（方案 2.3）
