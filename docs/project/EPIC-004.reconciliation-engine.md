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

**✅ 你的回答**: A - 全局固定阈值，等有真实数据后再考虑优化

**决策**: 第一版使用固定阈值
- `AUTO_ACCEPT_THRESHOLD = 85`
- `REVIEW_QUEUE_THRESHOLD = 60`
- 这些值配置在环境变量中（便于后续调整）
- 使用 MVP 阶段真实匹配数据，分析准确率和用户反馈
- v1.5+ 再考虑动态阈值或按账户类型配置

### Q2: 未匹配流水的处理流程
> **问题**: 未匹配流水（得分 < 60）如何处理？

**✅ 你的回答**: C - AI 建议分录模板。并且这些规则是时间敏感的，可能在特定时期内生效。

**决策**: AI 驱动的分录建议 + 时间感知的规则
- **未匹配流水处理流程**:
  1. 流水匹配得分 < 60 时，触发 `suggest_journal_entry()` 服务
  2. 根据流水信息（金额、描述、日期、账户等）生成 AI 建议
  3. AI 建议包含:
     - 推荐账户组合（如 "消费时用 Expense + Liability"）
     - 推荐金额拆分（如 "本金 2000 + 利息 50"）
     - 推荐事件类型（salary, card_payment, transfer, fee 等）
  4. 用户可一键接受建议，或修改后手动创建
  
- **时间感知的规则机制**:
  - 建立 `ReconciliationRule` 表:
    ```
    id, user_id, rule_name, description, 
    conditions (JSONB), actions (JSONB),
    effective_from, effective_to, priority, is_enabled
    ```
  - 规则示例:
    ```json
    {
      "name": "工资入账规则（仅 1-3 月）",
      "conditions": {
        "description_contains": ["SALARY", "EMPLOYER"],
        "amount_range": [4000, 6000],
        "date_in_months": [1, 2, 3]
      },
      "actions": {
        "account_debit": "Bank Main",
        "account_credit": "Income Salary",
        "auto_match_boost": 20
      },
      "effective_from": "2025-01-01",
      "effective_to": "2025-03-31"
    }
    ```
  - 对账时，加载有效期内的规则，增强 AI 建议的准确性
  - 用户可自定义规则（UI 提供规则编辑器）
  - 系统学习用户历史接受的建议，逐步改进建议质量

### Q3: 重复匹配检测
> **问题**: 一笔流水已匹配后，是否允许修改或重新匹配？

**✅ 你的回答**: C + 高级架构 - 用两层数据模型：
- 原始层（Account Event）：保留完整历史，不可修改
- 分析层（Ontology Event）：支持多版本映射，1:N 和 N:1 关系

**决策**: 双层事件模型 - 不可变原始层 + 可变分析层

**数据模型**:
```
BankStatementTransaction (原始层)
├─ id (UUID)
├─ statement_id
├─ txn_date, amount, direction, description
├─ created_at (IMMUTABLE)
└─ status: pending/matched/unmatched

ReconciliationMatch v1 (分析层，多版本)
├─ id (UUID)
├─ bank_txn_id (FK)
├─ journal_entry_ids[] (支持多个)
├─ match_score
├─ version (int)
├─ created_at
├─ superseded_by_id (指向下一版本)
└─ status: active/superseded/rejected

JournalEntry (原始层)
├─ id (UUID)
├─ entry_date, memo
├─ created_at (IMMUTABLE)
└─ matched_by_id[] (指向当前活跃的 ReconciliationMatch)
```

**匹配流程**（支持版本演化）:
1. 新匹配创建 `ReconciliationMatch v1`
2. 用户修改匹配时：
   - 创建新版本 `ReconciliationMatch v2`（不是覆盖 v1）
   - v1.superseded_by_id = v2.id
   - v1.status = superseded
3. 用户将一笔流水拆分为多笔分录时：
   - 原 `ReconciliationMatch v1` 作废（多对一 → 一对多）
   - 创建多条新 `ReconciliationMatch` 记录，每条关联不同分录
4. 用户合并多笔流水到一笔分录时：
   - 多条原 ReconciliationMatch 标记为 superseded
   - 创建新版本关联所有流水

**查询时的规则**:
- 前端显示当前活跃匹配：status='active' 且 superseded_by_id IS NULL
- 报表计算时仅计入活跃匹配
- 审计查询时可看完整版本历史

**好处**:
- ✅ 原始数据永不丢失（金融合规）
- ✅ 支持任意 N:M 匹配关系
- ✅ 完整的修改审计轨迹
- ✅ 支持规则演化（同一流水在不同时期有不同分类）

### Q4: 批量操作的安全限制
> **问题**: 批量确认是否需要额外验证？

**✅ 你的回答**: C - 仅允许批量确认高分项（≥ 80），低分项需逐个确认

**决策**: 分层批量操作策略
- **高分快速通道** (score ≥ 80):
  - 支持一键批量确认所有高分项
  - 可按日期范围、金额范围筛选后批量操作
  - UI 显示待确认总数和总金额
- **低分逐个确认** (60 ≤ score < 80):
  - 必须逐个审核，不支持批量操作
  - 前端列表仅允许单个确认/拒绝
  - 强制用户看到每笔交易的详情
- **批量操作确认对话**:
  - 弹窗显示：待批量确认数量、总金额、日期范围
  - 显示示例（前 5 笔）
  - 用户必须勾选 "我已审查上述信息" 才能确认
- **操作审计**:
  - 每个批量操作记录操作者、时间、确认数量
  - 支持批量撤销（仅在 24 小时内可撤销批量确认）

### Q5: 历史模式学习
> **问题**: 是否根据用户历史匹配行为调整算法？

**✅ 你的回答**: B + embedding - 简单规则学习，用 embedding 做相似度匹配

**决策**: Embedding 驱动的智能匹配 (简单高效)

**实现方案**:
- **Embedding 层** (使用开源模型，如 sentence-transformers):
  - 对每条 BankStatementTransaction 的描述生成 embedding
  - 对每条 JournalEntry 的 memo 生成 embedding
  - 计算两者的余弦相似度，作为"描述相似度"评分的增强
  
- **商户模式学习** (简单规则):
  - 维护 `MerchantPattern` 表:
    ```
    merchant_name, canonical_merchant,
    preferred_account_id, confidence,
    last_matched_at, match_count
    ```
  - 每次用户确认匹配时，更新模式:
    ```
    IF MERCHANT 已存在:
      UPDATE match_count, confidence
    ELSE:
      INSERT 新商户模式
    ```
  - 下次遇到同商户流水时，直接跳过低分候选，优先推荐历史账户
  
- **时间模式识别** (订阅类交易):
  - 识别固定周期交易（如每月同一天、金额固定）
  - 给予加分（如 +10 分）
  - 示例：每月 25 日的 500 SGD 租赁费
  
- **Integration**:
  ```
  score = 40% amount_match 
        + 25% date_match 
        + 20% embedding_similarity  // NEW
        + 10% business_logic 
        + 5% pattern_bonus        // 商户模式 + 时间模式
  ```

**数据表**:
```sql
-- 商户模式学习
CREATE TABLE merchant_patterns (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    merchant_name VARCHAR(255),
    canonical_merchant VARCHAR(255),
    preferred_account_id UUID,
    confidence DECIMAL(3,2),  -- 0-1
    match_count INT,
    last_matched_at TIMESTAMP
);

-- Embedding 缓存
CREATE TABLE transaction_embeddings (
    id UUID PRIMARY KEY,
    source_type ENUM ('bank_txn', 'journal_entry'),
    source_id UUID,
    embedding VECTOR(384),  -- pgvector extension
    created_at TIMESTAMP
);
```

**好处**:
- ✅ 简单，无需复杂 ML 框架
- ✅ 解决大部分模式识别问题（商户识别、类似交易）
- ✅ 可逐步优化（先用固定 embedding，后续可微调）
- ✅ 支持多语言（embedding 模型通常多语言）
- ✅ 性能好（向量相似度计算快）

---

## 📅 时间线

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| Week 1 | 数据模型 + 基础匹配算法 | 16h |
| Week 2 | 评分维度实现 + 特殊场景 | 20h |
| Week 3 | 审核队列 + 异常检测 | 16h |
| Week 4 | 前端界面 + 调优测试 | 20h |

**总预计**: 72 小时 (4 周)
