# EPIC-004: 对账引擎与匹配算法

> **Status**: ⏳ Pending  
> **Phase**: 3  
> **周期**: 4 周  
> **依赖**: EPIC-003  

---

## 🎯 目标

自动匹配银行流水与总账分录，实现智能对账与审核队列，达到 ≥95% 的自动匹配准确率。

**核心规则**:
```
≥ 85 分  → 自动接受
60-84 分 → 审核队列
< 60 分  → 未匹配
```

---

## 👥 角色审议

| 角色 | 关注点 | 审议意见 |
|------|--------|----------|
| 🔗 **Reconciler** | 匹配算法 | 多维度加权评分，阈值可调，支持一对多/多对一 |
| 🏗️ **Architect** | 系统设计 | 匹配引擎独立服务，支持批量处理和增量匹配 |
| 📊 **Accountant** | 业务合理性 | 账户类型组合必须符合会计逻辑（如工资=Bank+Income） |
| 💻 **Developer** | 性能要求 | 10,000 笔流水匹配 < 10s，支持并行处理 |
| 🧪 **Tester** | 准确率验证 | 误匹配率 < 0.5%，漏匹配率 < 2% |
| 📋 **PM** | 用户体验 | 审核队列高效易用，批量操作支持 |

---

## ✅ 任务清单

### 数据模型 (Backend)

- [ ] `ReconciliationMatch` 模型
  - `bank_txn_id` - 银行流水 ID
  - `journal_entry_ids` - 关联分录 ID（支持多个）
  - `match_score` - 综合得分 (0-100)
  - `score_breakdown` - 各维度得分 (JSONB)
  - `status` - 状态 (auto_accepted/pending_review/accepted/rejected)
- [ ] Alembic 迁移脚本
- [ ] 状态更新触发器（更新 JournalEntry 和 BankStatementTransaction 状态）

### 匹配算法 (Backend)

- [ ] `services/reconciliation.py` - 对账引擎
  - [ ] `calculate_match_score()` - 综合评分
  - [ ] `find_candidates()` - 查找候选分录
  - [ ] `execute_matching()` - 批量匹配执行
  - [ ] `auto_accept()` - 自动接受逻辑
- [ ] 评分维度实现
  - [ ] `score_amount()` - 金额匹配 (40%)
  - [ ] `score_date()` - 日期相近度 (25%)
  - [ ] `score_description()` - 描述相似度 (20%)
  - [ ] `score_business_logic()` - 业务合理性 (10%)
  - [ ] `score_pattern()` - 历史模式 (5%)
- [ ] 特殊场景处理
  - [ ] 一对多匹配（1 笔流水 → 多笔分录）
  - [ ] 多对一匹配（多笔流水 → 1 笔分录）
  - [ ] 跨期匹配（月末/月初）
  - [ ] 手续费拆分

### 审核队列 (Backend)

- [ ] `services/review_queue.py` - 审核队列管理
  - [ ] `get_pending_items()` - 获取待审核项（分页、排序）
  - [ ] `accept_match()` - 确认匹配
  - [ ] `reject_match()` - 拒绝匹配
  - [ ] `batch_accept()` - 批量确认
  - [ ] `create_entry_from_txn()` - 从流水创建分录

### 异常检测 (Backend)

- [ ] `services/anomaly.py` - 异常检测
  - [ ] 金额异常（> 10x 月均）
  - [ ] 频率异常（同商户 > 5 笔/天）
  - [ ] 时间异常（非工作时间大额）
  - [ ] 新商户标记

### API 端点 (Backend)

- [ ] `POST /api/reconciliation/run` - 执行对账匹配
- [ ] `GET /api/reconciliation/matches` - 匹配结果列表
- [ ] `GET /api/reconciliation/pending` - 待审核队列
- [ ] `POST /api/reconciliation/matches/{id}/accept` - 确认匹配
- [ ] `POST /api/reconciliation/matches/{id}/reject` - 拒绝匹配
- [ ] `POST /api/reconciliation/batch-accept` - 批量确认
- [ ] `GET /api/reconciliation/stats` - 对账统计
- [ ] `GET /api/reconciliation/unmatched` - 未匹配流水

### 前端界面 (Frontend)

- [ ] `/reconciliation` - 对账工作台
  - [ ] 对账概览（匹配率、未匹配数）
  - [ ] 待审核列表（排序、筛选）
  - [ ] 匹配详情（得分明细、候选分录）
  - [ ] 确认/拒绝操作
  - [ ] 批量操作工具栏
- [ ] `/reconciliation/unmatched` - 未匹配处理
  - [ ] 未匹配流水列表
  - [ ] 手动创建分录入口
  - [ ] 忽略/标记功能
- [ ] 可视化
  - [ ] 对账进度条
  - [ ] 匹配得分分布图
  - [ ] 异常交易高亮

---

## 📏 做得好不好的标准

### 🟢 合格标准 (Must Have)

| 标准 | 验证方法 | 权重 |
|------|----------|------|
| **自动匹配准确率 ≥ 95%** | 真实数据测试集验证 | 🔴 关键 |
| **误匹配率 < 0.5%** | 人工抽检 100 笔 | 🔴 关键 |
| **漏匹配率 < 2%** | 应匹配但未匹配的比例 | 🔴 关键 |
| 阈值可配置 | 参数化设计 | 必须 |
| 一对多匹配支持 | 测试场景验证 | 必须 |
| 批量处理 10,000 笔 < 10s | 性能测试 | 必须 |
| 匹配后状态正确更新 | JournalEntry/BankTxn 状态检查 | 必须 |

### 🌟 优秀标准 (Nice to Have)

| 标准 | 验证方法 | 状态 |
|------|----------|------|
| 自动匹配率 > 70% | 减少人工审核 | ⏳ |
| 审核队列平均处理时间 < 30s/笔 | 用户行为统计 | ⏳ |
| 异常检测召回率 > 95% | 标记异常覆盖度 | ⏳ |
| 机器学习权重调优 | 基于历史数据优化 | ⏳ |
| 匹配规则可视化配置 | 管理界面 | ⏳ |

### 🚫 不合格信号

- 误匹配率 > 2%（严重污染账本）
- 准确率 < 90%（失去自动化意义）
- 性能超时（批量处理 > 60s）
- 审核队列积压严重
- 用户无法理解匹配得分

---

## 🧪 测试场景

### 匹配算法测试 (必须)

```python
# 精确匹配
def test_exact_match_high_score():
    """金额、日期、描述完全匹配 → 得分 ≥ 95"""

def test_fuzzy_date_match():
    """日期差 2 天 → 得分 85-94"""

def test_amount_tolerance():
    """金额差 0.05（手续费） → 得分 80-90"""

# 多笔匹配
def test_one_to_many_match():
    """1 笔还款 1000 = 3 笔消费 (400+350+250)"""

def test_many_to_one_match():
    """3 笔小额流水 = 1 笔批量付款"""

# 边界情况
def test_cross_month_match():
    """1/31 转出 → 2/1 到账，应可匹配"""

def test_no_match_low_score():
    """完全不相关 → 得分 < 60"""
```

### 业务逻辑测试 (必须)

```python
def test_salary_pattern():
    """工资入账：Bank DEBIT + Income CREDIT"""

def test_credit_card_pattern():
    """信用卡还款：Liability DEBIT + Bank CREDIT"""

def test_invalid_pattern_penalty():
    """不合理组合（如 Income + Expense）应降分"""
```

### 性能测试 (必须)

```python
def test_batch_10000_transactions():
    """10,000 笔流水匹配 < 10s"""

def test_concurrent_matching():
    """并发对账不产生数据竞争"""
```

---

## 📚 SSOT 引用

- [schema.md](../ssot/schema.md) - ReconciliationMatch 表
- [reconciliation.md](../ssot/reconciliation.md) - 对账规则
- [reconciler.md](../../.claude/skills/reconciler.md) - 匹配算法设计

---

## 🔗 交付物

- [ ] `apps/backend/src/models/reconciliation.py`
- [ ] `apps/backend/src/services/reconciliation.py`
- [ ] `apps/backend/src/services/review_queue.py`
- [ ] `apps/backend/src/services/anomaly.py`
- [ ] `apps/backend/src/routers/reconciliation.py`
- [ ] `apps/frontend/app/reconciliation/page.tsx`
- [ ] 更新 `docs/ssot/reconciliation.md` (算法说明)
- [ ] 对账准确率报告

---

## 📝 技术债务

| 项目 | 优先级 | 计划解决时间 |
|------|--------|--------------|
| ML 权重自动调优 | P2 | v2.0 |
| 多币种匹配 | P2 | EPIC-005 后 |
| 实时匹配（流水入库即匹配） | P3 | 后续迭代 |

---

## ❓ Q&A (待确认问题)

### Q1: 匹配阈值是否可调
> **问题**: 85/60 的阈值是固定的，还是用户可以调整？  
> **选项**:
> - A) 全局固定阈值
> - B) 用户可在设置中调整
> - C) 按账户类型设置不同阈值
>
> **影响**: 影响配置管理和 UI 设计  
> **建议**: 选择 A，先用固定阈值验证算法效果

**你的回答**: _________________

### Q2: 未匹配流水的处理流程
> **问题**: 未匹配流水（得分 < 60）如何处理？  
> **选项**:
> - A) 仅标记，等待用户手动创建分录
> - B) 自动创建草稿分录（用户确认）
> - C) 提供 AI 建议的分录模板
>
> **影响**: 影响用户工作量和自动化程度  
> **建议**: 选择 C，AI 辅助但用户确认

**你的回答**: _________________

### Q3: 重复匹配检测
> **问题**: 如果一笔流水已匹配，后续是否允许修改？  
> **选项**:
> - A) 不允许修改，需先取消原匹配
> - B) 允许重新匹配（覆盖旧匹配）
> - C) 保留历史，新匹配作为新版本
>
> **影响**: 影响数据模型和审计日志  
> **建议**: 选择 A，保证数据一致性

**你的回答**: _________________

### Q4: 批量操作的安全限制
> **问题**: 批量确认是否需要额外验证？  
> **选项**:
> - A) 无限制，一键确认所有
> - B) 单次最多 100 笔
> - C) 仅允许批量确认高分项（≥ 80）
>
> **影响**: 影响误操作风险  
> **建议**: 选择 C，平衡效率和安全

**你的回答**: _________________

### Q5: 历史模式学习
> **问题**: 是否根据用户历史匹配行为调整算法？  
> **选项**:
> - A) 不学习，使用固定规则
> - B) 简单规则学习（如常见商户→账户映射）
> - C) ML 模型持续学习
>
> **影响**: 影响算法复杂度和开发周期  
> **建议**: 第一版选择 B，后续迭代选择 C

**你的回答**: _________________

---

## 📅 时间线

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| Week 1 | 数据模型 + 基础匹配算法 | 16h |
| Week 2 | 评分维度实现 + 特殊场景 | 20h |
| Week 3 | 审核队列 + 异常检测 | 16h |
| Week 4 | 前端界面 + 调优测试 | 20h |

**总预计**: 72 小时 (4 周)
