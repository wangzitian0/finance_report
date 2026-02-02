# 🚀 智能测试策略：快速 + 高标准

## 核心理念

> **变更文件跑覆盖率（99%），全量测试不带覆盖率**

✅ **快速**：全量测试无覆盖率开销（预计提速 60-70%）  
✅ **严格**：变更代码必须达到 99% 覆盖率  
✅ **安全**：所有测试都会执行，确保没有破坏现有功能

---

## 使用方法

### 🎯 推荐：智能测试（日常开发）

```bash
moon run backend:test-smart
```

**工作原理**：
1. 检测 Git 变更的 Python 文件
2. 如果有变更：
   - ✅ 运行**所有测试**（快速，无覆盖率）
   - ✅ 仅对**变更文件**收集覆盖率（要求 99%）
3. 如果无变更：
   - 回退到完整覆盖率测试（94%）

### ⚡ 极速模式：完全跳过覆盖率

```bash
moon run backend:test-no-cov
```

**适用场景**：
- 快速验证测试是否通过
- TDD 红绿重构循环
- 预计提速 **60-70%**

### 📊 完整模式：所有文件覆盖率

```bash
moon run backend:test-execution
```

**适用场景**：
- CI 流水线
- 提交前最终检查
- 重构后验证

---

## 📈 性能对比

| 模式 | 命令 | 执行时间 | 覆盖率检查 | 适用场景 |
|------|------|---------|-----------|---------|
| **智能模式** | `test-smart` | **~40%** ⚡ | 变更文件 99% | **日常开发（推荐）** |
| 极速模式 | `test-no-cov` | **~30%** 🚀 | 无 | 快速验证 |
| 快速模式 | `test-execution-fast` | ~65% | 全部 94% | 提交前检查 |
| 完整模式 | `test-execution` | 100% | 全部 94% | CI 流水线 |

---

## 🔍 工作原理详解

### 变更检测逻辑

脚本 `scripts/get_changed_files.py` 按优先级检测变更：

1. **分支差异**: `git diff main...HEAD` - 当前分支 vs main
2. **未提交变更**: `git diff HEAD` - 工作区改动
3. **暂存变更**: `git diff --cached` - 已 git add 的文件

### 覆盖率计算

```bash
# 假设你修改了 src/services/reconciliation.py

# 智能模式只检查这个文件的覆盖率：
pytest --cov=src.services.reconciliation \
       --cov-fail-under=99 \
       -n auto \
       tests/  # 但运行所有测试！
```

**关键优势**：
- 所有 912 个测试都会执行（保证没破坏任何功能）
- 但只收集变更文件的覆盖率（节省 60% 时间）
- 对变更代码要求更高（99% vs 94%）

---

## 🎓 使用场景示例

### 场景 1: 添加新功能

```bash
# 1. 修改 src/services/reconciliation.py
# 2. 运行智能测试
moon run backend:test-smart

# 输出示例：
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

### 场景 2: 重构现有代码

```bash
# 1. 重构 src/models/account.py 和 src/services/accounting.py
# 2. 运行智能测试
moon run backend:test-smart

# 输出示例：
# ⚡ Smart mode: Full tests + Coverage on changed files only
#   • src.models.account
#   • src.services.accounting
#
# Coverage:
#   src/models/account.py: 100%
#   src/services/accounting.py: 98%
```

### 场景 3: 修复配置文件（无代码变更）

```bash
# 1. 修改 pyproject.toml
# 2. 运行智能测试
moon run backend:test-smart

# 输出示例：
# ✅ No source changes detected - running full coverage
# ========== 912 passed in 120s ==========
# Coverage: 94.2%
```

---

## 🛡️ 质量保证

### 为什么这个策略不会降低质量？

1. **所有测试都执行** ✅
   - 无论覆盖率如何配置，所有 912 个测试都会运行
   - 变更不会破坏现有功能

2. **新代码更严格** ✅
   - 变更文件要求 **99%** 覆盖率（原来是 94%）
   - 保证新功能有充分测试

3. **回归保护** ✅
   - 全量测试确保没有意外破坏
   - 即使跳过覆盖率收集，测试失败仍会报错

---

## 🔧 手动控制

### 强制检查特定模块覆盖率

```bash
cd apps/backend
uv run pytest -n auto \
    --cov=src.services.reconciliation \
    --cov=src.services.accounting \
    --cov-fail-under=99 \
    --cov-report=term-missing
```

### 查看当前变更

```bash
python scripts/get_changed_files.py --format list
```

### 查看覆盖率参数

```bash
python scripts/get_changed_files.py --format pytest
```

---

## 📦 文件清单

```
scripts/
├── get_changed_files.py    # Git 变更检测脚本
├── smart_test.py           # 智能测试编排脚本
└── fast_test.py            # 极速测试（无覆盖率）

apps/backend/moon.yml
├── test-smart              # 智能模式（推荐）
├── test-no-cov             # 极速模式
├── test-execution-fast     # 快速模式
└── test-execution          # 完整模式（CI）
```

---

## 🎯 最佳实践

### 日常开发循环

```bash
# 1. TDD 红绿循环（最快）
moon run backend:test-no-cov

# 2. 功能完成后验证覆盖率
moon run backend:test-smart

# 3. 提交前最终检查（可选）
moon run backend:test-execution-fast
```

### CI 流水线

```bash
# 保持使用完整模式
moon run backend:test-execution
```

### 大规模重构

```bash
# 方式 1: 智能模式（推荐）
moon run backend:test-smart

# 方式 2: 手动指定重点模块
cd apps/backend
uv run pytest -n auto \
    --cov=src.services \
    --cov=src.models \
    --cov-fail-under=95
```

---

## ⚠️ 注意事项

### 覆盖率 99% 太严格？

可以调整 `scripts/smart_test.py` 中的阈值：

```python
# 第 66 行，改为 95%
"--cov-fail-under=95",
```

### 检测不到变更？

确保你的分支基于 `main`：

```bash
git fetch origin
git rebase origin/main
```

或者手动指定基准分支：

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
