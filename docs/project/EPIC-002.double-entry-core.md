# EPIC-002: Double-Entry Bookkeeping Core

> **Status**: 🟡 In Progress  
> **Phase**: 1  
> **Duration**: 3 周  
> **Dependencies**: EPIC-001  

---

## 🎯 Objective

实现符合Accounting equation 复式记账系统, 支持手工分录and账户管理。

**核心约束**:
```
Assets = Liabilities + Equity + (Income - Expenses)
SUM(DEBIT) = SUM(CREDIT)  // 每笔分录Required平衡
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | Accounting Correctness | Required严格遵循复式记账规则, 五大类账户借贷方向不能错 |
| 🏗️ **Architect** | Data Model | JournalEntry + JournalLine 模式支持一对多, 多对多场景 |
| 💻 **Developer** | Implementation Difficulty | 使用 Decimal 替代 float, 事务保证原子性 |
| 🧪 **Tester** | Validation Strategy | 100% 覆盖Balance validation逻辑, Boundary Tests (极端金额, 跨币种) |
| 📋 **PM** | User Value | 手工记账能力是后续自动化 基础, Priority最高 |

---

## ✅ Task Checklist

### Data Model (Backend)

- [ ] `Account` model - 五大类账户 (Asset/Liability/Equity/Income/Expense)
- [ ] `JournalEntry` model - 凭证头 (date, memo, status, source_type)
- [ ] `JournalLine` model - 分录行 (account_id, direction, amount, currency)
- [ ] Alembic 迁移脚本
- [ ] Pydantic Schema (请求/响应)

### API 端点 (Backend)

- [ ] `POST /api/accounts` - 创建账户
- [ ] `GET /api/accounts` - 账户列表 (支持 type 过滤)
- [ ] `GET /api/accounts/{id}` - 账户详情 (含余额)
- [ ] `PUT /api/accounts/{id}` - 更新账户
- [ ] `POST /api/journal-entries` - 创建分录 (含Balance validation)
- [ ] `GET /api/journal-entries` - 分录列表 (分页, 日期过滤)
- [ ] `GET /api/journal-entries/{id}` - 分录详情
- [ ] `POST /api/journal-entries/{id}/post` - 过账 (draft → posted)
- [ ] `POST /api/journal-entries/{id}/void` - 作废 (生成冲销分录)

### 业务逻辑 (Backend)

- [ ] `services/accounting.py` - 记账核心
  - [ ] `validate_journal_balance()` - 借贷Balance validation
  - [ ] `post_journal_entry()` - 过账逻辑
  - [ ] `calculate_account_balance()` - 账户余额计算
  - [ ] `verify_accounting_equation()` - Accounting equation验证
- [ ] 数据库约束 - CHECK 约束保证金额 > 0
- [ ] 事务处理 - 分录创建Required原子性

### 前端界面 (Frontend)

- [ ] `/accounts` - 账户管理页面
  - [ ] 账户列表 (按类型分组)
  - [ ] 创建账户表单
  - [ ] 账户详情侧边栏
- [ ] `/journal` - 分录管理页面
  - [ ] 分录列表 (可搜索, 分页)
  - [ ] 创建分录表单 (多行动态添加)
  - [ ] 分录详情弹窗
  - [ ] 过账/作废操作按钮

---

## 📏 做得好不好 标准

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Accounting equation 100% 满足** | `verify_accounting_equation()` 测试 | 🔴 关键 |
| **所有 posted 分录借贷平衡** | SQL 查询验证 + Unit tests | 🔴 关键 |
| **禁止 float 存储金额** | 代码审查 + grep 检查 | 🔴 关键 |
| 创建分录时自动验证平衡 | 不平衡返回 400 错误 | Required |
| 账户类型借贷方向正确 | 参考 accountant.md 规则 | Required |
| 过账后不可编辑 | 只能 void 后重做 | Required |
| API 响应时间 p95 < 200ms | 负载测试 | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Unit tests覆盖率 > 90% | coverage report | ⏳ |
| 支持多币种分录 | fx_rate field正确使用 | ⏳ |
| account codes支持 (1xxx-5xxx) | code field实现 | ⏳ |
| 分录模板功能 | 常用分录一键创建 | ⏳ |
| 前端实时Balance validation | 输入时显示借贷差额 | ⏳ |

### 🚫 Not Acceptable Signals

- posted 分录存在借贷不平衡
- Accounting equation不满足
- 使用 float 存储金额
- 过账后分录被修改
- API 返回 500 错误

---

## 🧪 Test Scenarios

### Unit tests (Required)

```python
# Balance validation
def test_balanced_entry_passes():
    """Balanced debit/credit entries should pass validation"""

def test_unbalanced_entry_fails():
    """Unbalanced entries should be rejected"""

def test_single_line_entry_fails():
    """Single-line entries should be rejected (minimum 2 lines)"""

# Accounting equation
def test_accounting_equation_after_posting():
    """Accounting equation should be satisfied after posting"""

# Amount precision
def test_decimal_precision():
    """Decimal calculations should not lose precision"""

def test_float_rejected():
    """Float type amounts not accepted"""
```

### Integration tests (Required)

```python
def test_create_salary_entry():
    """Salary deposit scenario: Bank DEBIT 5000 / Income CREDIT 5000"""

def test_create_credit_card_payment():
    """Credit card payment scenario: Liability DEBIT 200 / Bank CREDIT 200"""

def test_void_and_reverse():
    """Voided entries should generate reversal vouchers"""

def test_concurrent_posting():
    """Concurrent posting should not cause data inconsistencies"""
```

### Boundary Tests (Recommended)

```python
def test_max_amount():
    """Maximum amount 999,999,999.99"""

def test_min_amount():
    """Minimum amount 0.01"""

def test_many_lines_entry():
    """Multi-line entries (e.g., salary detail breakdown)"""
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
> **Question**: Should we enforce 1xxx-5xxx  account codes？or allow user customization？  
> **Impact**: Impact Account model `code` field 验证规则

**✅ Your Answer**: 使用 US GAAP Taxonomy 标准

**Decision**: Adopt US GAAP Taxonomy standard coding
- Follow international financial reporting standards
- Account model `code` fieldRequired符合 GAAP Taxonomy
- Frontend provides code lookup/selection tool
- Support custom aliases (user-friendly name)

### Q2: 多币种处理策略
> **Question**: Should v1 support multi-currency entries？or only support single base currency？  
> **Impact**: Impact JournalLine   `fx_rate` field使用方式

**✅ Your Answer**: C - Full multi-currency support, user-configurable base currency

**Decision**: V1 supports full multi-currency from the start
- Account model支持多币种配置
- JournalLine 每条都记录原币金额and汇率
- User can set personal base currency (default SGD)
- Reports convert based on user's base currency
- Historical exchange rate records (for retrospective calculations)

### Q3: 草稿分录是否counted余额
> **Question**: `draft` 状态 分录是否Impact账户余额显示？  
> **Impact**: Impact `calculate_account_balance()`  逻辑

**✅ Your Answer**: A - `draft` excluded, only `posted` and `reconciled` counted

**Decision**: 余额计算Only include posted entries
- `calculate_account_balance()` Filter condition: status IN ('posted', 'reconciled')
- Draft entries displayed in frontend as"pending posting", 但不Impact余额
- 用户Can preview draft entries in UI

### Q4: 作废分录 处理方式
> **Question**: Void by direct deletion or generate reversal vouchers？  
> **Impact**: Impact审计日志 完整性

**✅ Your Answer**: B - Generate reversal vouchers (red entries), automatically generate offsetting entries

**Decision**: Adopt reversal voucher approach (GAAP compliant)
- Call `void_journal_entry(entry_id)` system automatically generates a reversal voucher
- reversal voucherAll JournalLine opposite direction, same amount
- Original entry status changed to void, linked to reversal voucher ID
- Preserve complete audit trail, comply with financial regulations
- Frontend displays"voided (reversal voucher ID: xxx)"

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + API 骨架 | 16h |
| Week 2 | 业务逻辑 + 测试 | 20h |
| Week 3 | 前端界面 + 集成 | 16h |

**总预计**: 52 小时 (3 周)
