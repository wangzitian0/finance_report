# EPIC-002: Double-Entry Bookkeeping Core

> **Status**: 🟡 In Progress  
> **Phase**: 1  
> **Duration**: 3 周  
> **Dependencies**: EPIC-001  

---

## 🎯 Objective

实现符合会计恒等式的复式记账系统，支持手工分录与账户管理。

**核心约束**:
```
Assets = Liabilities + Equity + (Income - Expenses)
SUM(DEBIT) = SUM(CREDIT)  // 每笔分录必须平衡
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | 会计正确性 | 必须严格遵循复式记账规则，五大类账户借贷方向不能错 |
| 🏗️ **Architect** | 数据模型 | JournalEntry + JournalLine 模式支持一对多、多对多场景 |
| 💻 **Developer** | 实现难度 | 使用 Decimal 替代 float，事务保证原子性 |
| 🧪 **Tester** | 验证策略 | 100% 覆盖平衡验证逻辑，边界测试（极端金额、跨币种） |
| 📋 **PM** | 用户价值 | 手工记账能力是后续自动化的基础，优先级最高 |

---

## ✅ Task Checklist

### 数据模型 (Backend)

- [ ] `Account` 模型 - 五大类账户 (Asset/Liability/Equity/Income/Expense)
- [ ] `JournalEntry` 模型 - 凭证头 (date, memo, status, source_type)
- [ ] `JournalLine` 模型 - 分录行 (account_id, direction, amount, currency)
- [ ] Alembic 迁移脚本
- [ ] Pydantic Schema (请求/响应)

### API 端点 (Backend)

- [ ] `POST /api/accounts` - 创建账户
- [ ] `GET /api/accounts` - 账户列表 (支持 type 过滤)
- [ ] `GET /api/accounts/{id}` - 账户详情（含余额）
- [ ] `PUT /api/accounts/{id}` - 更新账户
- [ ] `POST /api/journal-entries` - 创建分录 (含平衡验证)
- [ ] `GET /api/journal-entries` - 分录列表 (分页、日期过滤)
- [ ] `GET /api/journal-entries/{id}` - 分录详情
- [ ] `POST /api/journal-entries/{id}/post` - 过账 (draft → posted)
- [ ] `POST /api/journal-entries/{id}/void` - 作废 (生成冲销分录)

### 业务逻辑 (Backend)

- [ ] `services/accounting.py` - 记账核心
  - [ ] `validate_journal_balance()` - 借贷平衡验证
  - [ ] `post_journal_entry()` - 过账逻辑
  - [ ] `calculate_account_balance()` - 账户余额计算
  - [ ] `verify_accounting_equation()` - 会计恒等式验证
- [ ] 数据库约束 - CHECK 约束保证金额 > 0
- [ ] 事务处理 - 分录创建必须原子性

### 前端界面 (Frontend)

- [ ] `/accounts` - 账户管理页面
  - [ ] 账户列表（按类型分组）
  - [ ] 创建账户表单
  - [ ] 账户详情侧边栏
- [ ] `/journal` - 分录管理页面
  - [ ] 分录列表（可搜索、分页）
  - [ ] 创建分录表单（多行动态添加）
  - [ ] 分录详情弹窗
  - [ ] 过账/作废操作按钮

---

## 📏 做得好不好的标准

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **会计恒等式 100% 满足** | `verify_accounting_equation()` 测试 | 🔴 关键 |
| **所有 posted 分录借贷平衡** | SQL 查询验证 + 单元测试 | 🔴 关键 |
| **禁止 float 存储金额** | 代码审查 + grep 检查 | 🔴 关键 |
| 创建分录时自动验证平衡 | 不平衡返回 400 错误 | 必须 |
| 账户类型借贷方向正确 | 参考 accountant.md 规则 | 必须 |
| 过账后不可编辑 | 只能 void 后重做 | 必须 |
| API 响应时间 p95 < 200ms | 负载测试 | 必须 |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| 单元测试覆盖率 > 90% | coverage report | ⏳ |
| 支持多币种分录 | fx_rate 字段正确使用 | ⏳ |
| 科目编码支持 (1xxx-5xxx) | code 字段实现 | ⏳ |
| 分录模板功能 | 常用分录一键创建 | ⏳ |
| 前端实时平衡验证 | 输入时显示借贷差额 | ⏳ |

### 🚫 Not Acceptable Signals

- posted 分录存在借贷不平衡
- 会计恒等式不满足
- 使用 float 存储金额
- 过账后分录被修改
- API 返回 500 错误

---

## 🧪 Test Scenarios

### 单元测试 (必须)

```python
# 平衡验证
def test_balanced_entry_passes():
    """借贷相等的分录应通过验证"""

def test_unbalanced_entry_fails():
    """借贷不等的分录应被拒绝"""

def test_single_line_entry_fails():
    """单行分录应被拒绝（至少2行）"""

# 会计恒等式
def test_accounting_equation_after_posting():
    """过账后会计恒等式应满足"""

# 金额精度
def test_decimal_precision():
    """Decimal 计算不应丢失精度"""

def test_float_rejected():
    """不接受 float 类型金额"""
```

### 集成测试 (必须)

```python
def test_create_salary_entry():
    """工资入账场景: Bank DEBIT 5000 / Income CREDIT 5000"""

def test_create_credit_card_payment():
    """信用卡还款场景: Liability DEBIT 200 / Bank CREDIT 200"""

def test_void_and_reverse():
    """作废分录应生成冲销凭证"""

def test_concurrent_posting():
    """并发过账不应产生数据不一致"""
```

### 边界测试 (建议)

```python
def test_max_amount():
    """最大金额 999,999,999.99"""

def test_min_amount():
    """最小金额 0.01"""

def test_many_lines_entry():
    """多行分录（如工资明细拆分）"""
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - 数据库表结构
- [accounting.md](../ssot/accounting.md) - 会计规则
- [accountant.md](../../.claude/skills/accountant.md) - 典型分录映射

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/account.py`
- [ ] `apps/backend/src/models/journal.py`
- [ ] `apps/backend/src/services/accounting.py`
- [ ] `apps/backend/src/routers/accounts.py`
- [ ] `apps/backend/src/routers/journal.py`
- [ ] `apps/frontend/app/accounts/page.tsx`
- [ ] `apps/frontend/app/journal/page.tsx`
- [ ] 更新 `docs/ssot/schema.md` (ER 图)
- [ ] 更新 `docs/ssot/accounting.md` (API 说明)

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| 多币种余额折算 | P2 | EPIC-005 |
| 科目层级树 | P3 | 后续迭代 |
| 分录批量导入 | P3 | 后续迭代 |

---

## ❓ Q&A (Clarification Required)

### Q1: 账户编码规范
> **问题**: 是否需要强制使用 1xxx-5xxx 的科目编码？还是用户可以自定义？  
> **影响**: 影响 Account 模型 `code` 字段的验证规则

**✅ 你的回答**: 使用 US GAAP Taxonomy 标准

**决策**: 采用 US GAAP Taxonomy 标准编码
- 遵循国际财务报告规范
- Account 模型 `code` 字段必须符合 GAAP Taxonomy
- 前端提供编码查询/选择工具
- 支持自定义别名（user-friendly name）

### Q2: 多币种处理策略
> **问题**: 第一版是否需要支持多币种分录？还是仅支持单一记账本位币？  
> **影响**: 影响 JournalLine 的 `fx_rate` 字段使用方式

**✅ 你的回答**: C - 完全多币种支持，用户自选记账本位币

**决策**: 第一版即支持完全多币种
- Account 模型支持多币种配置
- JournalLine 每条都记录原币金额和汇率
- 用户可设置个人记账本位币（默认 SGD）
- 报表基于用户本位币折算
- 汇率历史记录（用于回溯计算）

### Q3: 草稿分录是否计入余额
> **问题**: `draft` 状态的分录是否影响账户余额显示？  
> **影响**: 影响 `calculate_account_balance()` 的逻辑

**✅ 你的回答**: A - `draft` 不计入，只有 `posted` 和 `reconciled` 计入

**决策**: 余额计算仅包含已过账分录
- `calculate_account_balance()` 过滤条件: status IN ('posted', 'reconciled')
- 草稿分录前端展示为"待过账"，但不影响余额
- 用户可在 UI 中查看草稿分录预览

### Q4: 作废分录的处理方式
> **问题**: 作废是直接删除，还是生成冲销凭证？  
> **影响**: 影响审计日志的完整性

**✅ 你的回答**: B - 生成冲销凭证（红字凭证），自动生成对冲分录

**决策**: 采用冲销凭证模式（符合 GAAP 标准）
- 调用 `void_journal_entry(entry_id)` 时，系统自动生成一张冲销凭证
- 冲销凭证的所有 JournalLine 方向相反，金额相同
- 原分录状态改为 void，关联冲销凭证 ID
- 保留完整审计轨迹，符合财务规范
- 前端显示"已作废（冲销凭证 ID: xxx）"

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | 数据模型 + API 骨架 | 16h |
| Week 2 | 业务逻辑 + 测试 | 20h |
| Week 3 | 前端界面 + 集成 | 16h |

**总预计**: 52 小时 (3 周)
