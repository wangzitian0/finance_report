# 测试执行优化指南

## 🐌 当前问题
- 912 个测试，执行时间过长
- 使用 `--dist loadfile` 策略可能不够高效
- 生成多个覆盖率报告（lcov + term-missing）增加开销

## 🚀 优化方案

### 方案 1: 使用 worksteal 分发策略（已应用）
**改进**: 将 `--dist loadfile` 改为 `--dist worksteal`

```bash
# 原来的命令
pytest -n auto --dist loadfile

# 优化后的命令
pytest -n auto --dist worksteal
```

**效果**: `worksteal` 动态分配测试到空闲的 worker，比 `loadfile`（按文件分配）更均衡，**预计提速 20-30%**

---

### 方案 2: 新增快速测试任务（已添加）
**用途**: 开发时快速验证，跳过详细的覆盖率报告

```bash
# 原来 - 生成详细报告
moon run backend:test-execution

# 快速模式 - 只显示简要覆盖率
moon run backend:test-execution-fast
```

**改进点**:
- 移除 `--cov-report=lcov` 和 `--cov-report=term-missing`
- 只保留 `--cov-report=term`（简要统计）
- 添加 `--tb=short`（简化错误输出）

**预计提速**: **10-15%**

---

### 方案 3: 使用 pytest-xdist 的智能缓存
**配置**: 在 `pyproject.toml` 中启用缓存

```toml
[tool.pytest.ini_options]
addopts = """
    --cov=src 
    --cov-report=term 
    --cov-branch 
    --cov-fail-under=94 
    -m 'not slow' 
    -n auto 
    --dist worksteal
    --maxfail=10
"""
```

**新增参数**:
- `--maxfail=10`: 失败 10 个测试后停止（快速失败）

---

### 方案 4: 分层测试执行
**思路**: 将测试分为多个级别，按需执行

```bash
# 1. 超快速烟雾测试（核心功能，<30s）
moon run backend:test-smoke

# 2. 快速测试（跳过慢测试，<2min）
moon run backend:test-execution-fast

# 3. 完整测试（包含详细报告，CI 使用）
moon run backend:test-execution
```

新增 `test-smoke` 任务：
```yaml
test-smoke:
  command: 'uv run pytest -n auto -m smoke -x --tb=short'
  local: true
```

---

### 方案 5: 跳过覆盖率检查（开发时）
**场景**: 快速迭代时不需要覆盖率

```bash
# 跳过覆盖率，纯测试执行
cd apps/backend
uv run pytest -n auto -v -m "not slow and not e2e" --tb=short
```

**预计提速**: **30-40%**（覆盖率收集有显著开销）

---

### 方案 6: 增加并行度（硬件充足时）
**当前**: `-n auto`（自动检测 CPU 核心数）

**优化**: 显式指定更多 worker

```bash
# 查看当前 CPU 核心数
sysctl -n hw.ncpu

# 假设有 8 核，可以尝试
pytest -n 12 ...  # 使用更多 worker（超线程）
```

⚠️ **注意**: 过多 worker 可能因数据库连接竞争而变慢

---

### 方案 7: 使用内存数据库（最激进）
**改进**: 测试时使用 SQLite 内存数据库代替 PostgreSQL

```python
# tests/conftest.py
@pytest.fixture
async def db_session():
    # 开发时用 SQLite
    if os.getenv("FAST_TEST"):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    else:
        # CI 用真实 PostgreSQL
        engine = create_async_engine(settings.DATABASE_URL)
```

**使用**:
```bash
FAST_TEST=1 moon run backend:test-execution-fast
```

**预计提速**: **50-70%**（但可能错过 PostgreSQL 特定 bug）

---

## 📊 性能对比（预估）

| 方案 | 执行时间 | 覆盖率 | 适用场景 |
|------|---------|--------|---------|
| 原配置 (loadfile) | 100% (基准) | ✅ 完整 | CI |
| Worksteal (方案1) | **~75%** | ✅ 完整 | CI |
| Fast模式 (方案2) | **~65%** | ✅ 简要 | 开发 |
| 无覆盖率 (方案5) | **~35%** | ❌ 无 | 快速验证 |
| 内存DB (方案7) | **~25%** | ✅ 完整 | 开发 |

---

## 🎯 推荐策略

### 日常开发（最快）
```bash
# 快速验证改动
moon run backend:test-execution-fast

# 或者不要覆盖率
cd apps/backend && uv run pytest -n auto -x --tb=line
```

### 提交前检查
```bash
# 完整验证
moon run backend:test-execution
```

### CI 流水线
```bash
# 保持现有配置（worksteal 已优化）
moon run backend:ci
```

---

## 🛠️ 已应用的改进

1. ✅ `test-execution`: 使用 `--dist worksteal`（替换 loadfile）
2. ✅ `test-execution-fast`: 新增快速测试任务
3. ⏳ `test-smoke`: 待添加（需要给核心测试打 `@pytest.mark.smoke` 标记）

---

## 📝 下一步

### 立即可用
```bash
# 试试新的 worksteal 配置
moon run backend:test-execution

# 或者用快速模式
moon run backend:test-execution-fast
```

### 进一步优化（可选）
1. 给核心测试打 `@pytest.mark.smoke` 标记，创建超快烟雾测试套件
2. 评估是否需要在开发时使用内存数据库
3. 分析哪些测试最慢，考虑标记为 `@pytest.mark.slow`

---

## 🔍 诊断慢测试

找出最慢的 10 个测试：
```bash
cd apps/backend
uv run pytest --durations=10 -m "not slow and not e2e"
```

找出所有 > 1s 的测试：
```bash
uv run pytest --durations=0 -m "not slow and not e2e" | grep -E "^\d+\.\d+s" | sort -rn
```
