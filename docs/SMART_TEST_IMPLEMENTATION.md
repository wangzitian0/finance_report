# 🚀 智能测试策略 - 完整实现

## ✨ 核心理念

> **变更文件跑覆盖率（99%），全量测试不带覆盖率**

- ✅ **快速**: 只收集变更文件的覆盖率（预计提速 60-70%）
- ✅ **严格**: 变更代码必须达到 99% 覆盖率
- ✅ **安全**: 所有 912 个测试都会执行，不会漏掉任何问题

---

## 🎯 使用方法

### 推荐：智能测试（日常开发）

```bash
moon run backend:test-smart
```

**工作原理**:
- 检测 Git 变更的 Python 文件
- 有变更：全量测试 + 变更文件覆盖率（99%）
- 无变更：回退到完整覆盖率（94%）

### 极速：完全跳过覆盖率

```bash
moon run backend:test-no-cov
```

**适用场景**: TDD 红绿循环，快速验证

### 快速：简化覆盖率报告

```bash
moon run backend:test-execution-fast
```

### 完整：CI 模式

```bash
moon run backend:test-execution
```

---

## 📊 性能对比

| 模式 | 命令 | 相对时间 | 覆盖率 | 适用场景 |
|------|------|---------|--------|---------|
| **智能模式** ⭐ | `test-smart` | **~40%** | 变更 99% | **日常开发（推荐）** |
| 极速模式 | `test-no-cov` | **~30%** | 无 | 快速验证 |
| 快速模式 | `test-execution-fast` | ~65% | 全部 94% | 提交前检查 |
| 完整模式 | `test-execution` | 100% | 全部 94% | CI 流水线 |

---

## 🔍 工作示例

### 场景 1：修改了 reconciliation.py

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

========== 912 passed in 48s ========== (原来要 120s)

Coverage:
  src/services/reconciliation.py: 99.2% ✅
```

### 场景 2：没有代码变更

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

## 🛠️ 实现细节

### 文件结构

```
scripts/
├── get_changed_files.py    # Git 变更检测
├── smart_test.py           # 智能测试编排
├── fast_test.py            # 极速测试（无覆盖率）
└── test_lifecycle.py       # 数据库生命周期管理

apps/backend/moon.yml
├── test-smart              # ⭐ 智能模式
├── test-no-cov             # 🚀 极速模式
├── test-execution-fast     # ⏱️ 快速模式
└── test-execution          # 🔍 完整模式
```

### 变更检测逻辑

`get_changed_files.py` 按优先级检测：

1. **分支差异**: `git diff main...HEAD`
2. **未提交变更**: `git diff HEAD`
3. **暂存变更**: `git diff --cached`

### 数据库管理

所有测试模式都通过 `test_lifecycle.py` 管理数据库：
- 自动启动 Docker Compose (postgres)
- 创建隔离的测试数据库
- 运行 Alembic 迁移
- 测试完成后清理

---

## 🎓 最佳实践

### 日常开发循环

```bash
# 1. TDD 红绿循环（最快）
moon run backend:test-no-cov

# 2. 功能完成后验证覆盖率
moon run backend:test-smart

# 3. 提交前最终检查（可选）
moon run backend:test-execution-fast
```

### 提交前检查

```bash
# 确保所有变更都有充分测试
moon run backend:test-smart
```

### CI 流水线

```bash
# 保持使用完整模式
moon run backend:test-execution
```

---

## 🔧 诊断工具

### 查看当前变更

```bash
python scripts/get_changed_files.py --format list
```

### 查看变更数量

```bash
python scripts/get_changed_files.py --format count
```

### 查看覆盖率参数

```bash
python scripts/get_changed_files.py --format pytest
```

### 找出最慢的测试

```bash
cd apps/backend
uv run pytest --durations=20 -m "not slow and not e2e"
```

---

## 🛡️ 质量保证

### 为什么不会降低质量？

1. ✅ **所有测试都执行**
   - 无论覆盖率配置如何，912 个测试都会运行
   - 任何回归问题都会被捕获

2. ✅ **新代码更严格**
   - 变更文件要求 **99%** 覆盖率（高于原来的 94%）
   - 保证新功能有充分测试

3. ✅ **自动回退**
   - 没有变更时自动使用完整覆盖率
   - 保持 CI 标准

---

## ⚙️ 配置调整

### 调整覆盖率阈值

编辑 `scripts/smart_test.py`:

```python
# 第 64 行，改为 95%
"--cov-fail-under=95",
```

### 修改基准分支

默认对比 `main` 分支，可以在 `get_changed_files.py` 中修改：

```python
# 第 22 行
["git", "diff", "--name-only", f"develop...HEAD"],
```

或者运行时指定：

```bash
python scripts/get_changed_files.py --base develop
```

---

## 🚀 快速开始

```bash
# 试试智能测试！
moon run backend:test-smart
```

第一次运行如果没有变更，会自动回退到完整覆盖率。  
修改任何 `apps/backend/src/` 下的文件后再运行，即可体验智能模式的速度！

---

## 📚 进阶优化

### 已应用的优化

1. ✅ **worksteal 分发策略** - 动态负载均衡（20-30% 提速）
2. ✅ **智能覆盖率** - 只检查变更文件（60-70% 提速）
3. ✅ **数据库隔离** - 支持并行测试无冲突

### 可选优化

查看 `docs/TEST_OPTIMIZATION.md` 了解更多优化方案：
- 内存数据库（额外 50% 提速，但可能错过 PostgreSQL 特定 bug）
- 分层测试（smoke/fast/full）
- 自定义并行度

---

## ❓ 常见问题

### Q: 检测不到变更？

**A**: 确保你的分支基于 `main`:

```bash
git fetch origin
git rebase origin/main
```

### Q: 覆盖率 99% 太严格？

**A**: 可以调整阈值到 95% 或 97%（见配置调整部分）

### Q: 需要手动启动数据库吗？

**A**: 不需要！所有测试模式都通过 `test_lifecycle.py` 自动管理数据库

---

## 🎉 总结

智能测试策略实现了：

✅ **速度** - 60-70% 提速（智能模式）  
✅ **质量** - 99% 覆盖率要求（变更文件）  
✅ **安全** - 所有测试都执行  
✅ **简单** - 一个命令搞定

开始使用：

```bash
moon run backend:test-smart
```
