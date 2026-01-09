# 📋 EPIC Q&A 决策总结

> **完成日期**: 2026-01-09  
> **分支**: `feat/epic-planning`  
> **状态**: ✅ 所有 24 个问题已回答并记录

---

## ✅ 完成状态

| 指标 | 数值 |
|------|------|
| 总问题数 | 24 个 |
| 已回答 | 24 个 (100%) |
| 已记录到文档 | ✅ EPIC-002 ~ EPIC-006 |
| 已提交分支 | ✅ feat/epic-planning |

---

## 🎯 关键决策汇总

### EPIC-002: 复式记账核心 (Q1-Q4)

| # | 问题 | 决策 |
|---|------|------|
| Q1 | 账户编码规范 | **US GAAP Taxonomy** - 国际财务标准 |
| Q2 | 多币种处理 | **完全支持** - 用户自选记账本位币 |
| Q3 | 草稿余额计算 | **不计入** - 仅 posted/reconciled 状态计入 |
| Q4 | 作废分录处理 | **冲销凭证** - 红字凭证保留审计日志 |

### EPIC-003: 智能对账单解析 (Q5-Q9)

| # | 问题 | 决策 |
|---|------|------|
| Q5 | 银行优先级 | **通用结构 + 扩展字段** - DBS/CITIC/Maybank/Wise/券商/保险 |
| Q6 | 成本控制 | **OpenRouter 层面** - $2/day 配额管理 |
| Q7 | 失败处理 | **分层重试** - Gemini 3 Flash → 强模型 → 人工编辑 |
| Q8 | 账户关联 | **AI建议 + 用户确认** - 解析 → 匹配推荐 → 用户确认 |
| Q9 | 历史导入 | **异步 ETL 任务队列** - 每个上传对应独立任务 |

### EPIC-004: 对账引擎与匹配算法 (Q10-Q14)

| # | 问题 | 决策 |
|---|------|------|
| Q10 | 阈值可调性 | **固定** (85/60) - 有真实数据后再优化 |
| Q11 | 未匹配处理 | **AI模板建议 + 时间敏感规则** - 支持规则按时期生效 |
| Q12 | 重复匹配 | **双层模型** - Account Event (不可变) + Ontology Event (多版本) |
| Q13 | 批量安全 | **分层批处理** - ≥80分支持批量，<80分逐个确认 |
| Q14 | 历史学习 | **Embedding向量 + 商户/时间模式** - 简单高效的模式识别 |

### EPIC-005: 财务报表与可视化 (Q15-Q19)

| # | 问题 | 决策 |
|---|------|------|
| Q15 | 报表期间 | **自然月** (1-31) - 最直观的周期 |
| Q16 | 汇率源 | **Yahoo Finance API** - 免费且准确 |
| Q17 | 历史汇率 | **交易日汇率** - 符合 GAAP 准则 |
| Q18 | 图表库 | **ECharts** - 支持 K 线等金融图表 |
| Q19 | 导出格式 | **CSV (数据导出) + PDF (格式报表)** - 分层输出 |

### EPIC-006: AI 财务顾问 (Q20-Q24)

| # | 问题 | 决策 |
|---|------|------|
| Q20 | API 可用性 | **错误提示** - 无降级方案，等待恢复 |
| Q21 | 历史记录 | **永久保留** - 用户可手动删除 |
| Q22 | 免责声明 | **首次弹窗** - 单次同意 + 持续提示 |
| Q23 | 调用限制 | **无限制** - OpenRouter 处理 $2/day 配额 |
| Q24 | 主动提醒 | **仅被动回答** - 用户主动提问，无推送 |

---

## 🔄 设计亮点

### 1️⃣ 架构创新

#### **双层事件模型** (EPIC-004 Q12)
```
BankStatementTransaction (Account Event - 不可变原始层)
  ↓ (多版本映射)
ReconciliationMatch v1, v2, v3, ... (Ontology Event - 可变分析层)
  ↓ (当前活跃)
JournalEntry

好处:
- 完整审计轨迹（原始数据永不丢失）
- 灵活的 N:M 映射（1对多、多对1、多对多）
- 规则演化（同一流水在不同时期可有不同分类）
```

#### **时间敏感规则引擎** (EPIC-004 Q11)
```
ReconciliationRule:
  - name: "工资入账规则（1-3月有效）"
  - conditions: {amount_range: [4000, 6000]}
  - effective_from: 2025-01-01
  - effective_to: 2025-03-31
  - actions: {account_debit: "Bank", account_credit: "Income Salary"}

应用: 对账时加载有效期内的规则，增强 AI 建议准确性
```

#### **异步 ETL 任务队列** (EPIC-003 Q9)
```
StatementProcessingTask:
  - 上传时创建任务记录
  - 独立异步处理（支持重试、优先级、进度跟踪）
  - 支持多文件并行处理
  - 用户可实时查看处理状态

优点: 高效批量导入、用户体验好
```

### 2️⃣ AI 集成智慧

#### **分层重试策略** (EPIC-003 Q7)
```
Upload PDF
  ↓
Try Gemini 3 Flash (快速、便宜)
  ├─ ✅ Success → 返回结果
  └─ ❌ Fail → 提示用户可重试
      ↓
      Try Gemini 2.0 / GPT-4 (更强模型)
      ├─ ✅ Success → 返回结果
      └─ ❌ Fail → 显示部分结果 + 编辑表单
```

#### **Embedding 向量匹配** (EPIC-004 Q14)
```
商户模式识别:
  MerchantPattern: {
    merchant_name: "Starbucks",
    preferred_account: "Living Expenses",
    confidence: 0.95,
    match_count: 23
  }

时间模式识别:
  - 每月 25 日 500 SGD → 租赁费
  - 每周五 100 SGD → 外卖

匹配评分:
  score = 40% amount + 25% date + 20% embedding + 10% logic + 5% pattern
```

#### **通用结构 + 扩展字段** (EPIC-003 Q5)
```
BankStatementTransaction:
  - 核心字段: txn_date, amount, direction, description
  - 扩展字段 (JSONB):
    - bank_specific_data: {交易码, 参考号, 终端号等}
    - institution_type: bank/brokerage/insurance/wallet
    - custom_fields: 用户自定义字段

Prompt 模板:
  templates/dbs.yaml
  templates/citic.yaml
  templates/brokerage_generic.yaml
  templates/insurance_generic.yaml
```

### 3️⃣ 金融合规

- **US GAAP 编码** → 国际财务标准
- **冲销凭证** → 审计日志完整性
- **交易日汇率** → GAAP 记账准则（而非报表日汇率）
- **Embedding 向量缓存** → 可回溯历史分类

### 4️⃣ 用户体验设计

#### **安全第一**
- 批量操作限制：≥80分支持批量，<80分逐个确认
- 批量确认弹窗显示总数、总金额、示例
- 24小时内可撤销批量操作

#### **渐进式交互**
- 解析 → AI 建议 → 用户确认（不强制）
- 账户关联：AI 推荐 → 用户确认（不自动）
- 未匹配流水：AI 建议模板 → 用户接受/修改

#### **被动 AI**
- 仅在用户主动提问时回答
- 不生成推送、通知、或主动提醒
- 用户完全掌控交互时机

---

## 📊 项目周期重估

基于决策方案的复杂度调整：

| EPIC | 原估 | 新估 | Δ | 理由 |
|------|------|------|---|------|
| EPIC-001 | 2w | 2w | → | 基础设施无变化 |
| EPIC-002 | 3w | 3w | → | GAAP/多币种/冲销凭证在预期内 |
| EPIC-003 | 3w | **4w** | +1w | 通用结构+ETL队列+多模型重试 |
| EPIC-004 | 4w | **5w** | +1w | 双层模型+embedding+规则引擎 |
| EPIC-005 | 3w | 3w | → | ECharts+PDF 难度不高 |
| EPIC-006 | 2w | 2w | → | 被动AI简化了实现 |
| **总计** | **15-18w** | **17-20w** | **+2w** | 架构升级值得额外投入 |

---

## 🚀 后续执行步骤

### Phase 1: 验证与审查 (Week 1)
- [ ] 技术审查决策方案（Architect 角色）
- [ ] 需求确认（PM 角色）
- [ ] 成本评估（是否增加 1-2 周可接受）

### Phase 2: 原型开发 (Week 2-3)
- [ ] EPIC-002 核心开发（优先级最高）
- [ ] EPIC-001 完善（pre-commit hooks, CI/CD）

### Phase 3: 数据积累 (Week 4-12)
- [ ] EPIC-003 对账单解析
- [ ] EPIC-004 对账引擎（关键算法调优需数据支撑）
- [ ] 积累真实对账数据

### Phase 4: 报表与 AI (Week 13-18)
- [ ] EPIC-005 财务报表
- [ ] EPIC-006 AI 财务顾问
- [ ] 基于数据反馈调整

### Phase 5: 反馈迭代 (v1.5+)
- [ ] 参数调优（阈值、权重）
- [ ] 新功能扩展（现金流表、预算管理）
- [ ] 性能优化（缓存、物化视图）

---

## 📑 相关文档

- [EPIC-002.double-entry-core.md](./EPIC-002.double-entry-core.md)
- [EPIC-003.statement-parsing.md](./EPIC-003.statement-parsing.md)
- [EPIC-004.reconciliation-engine.md](./EPIC-004.reconciliation-engine.md)
- [EPIC-005.reporting-visualization.md](./EPIC-005.reporting-visualization.md)
- [EPIC-006.ai-advisor.md](./EPIC-006.ai-advisor.md)

---

**记录者**: Zitian Wang  
**完成时间**: 2026-01-09 20:04 UTC  
**Git 提交**: `3ad0187`
