# 个人财务管理系统 - Moonrepo 项目计划书 v3.0

**规划日期**: 2026-01-09  
**总体周期**: 15-18 周 (3-4 个月)  
**技术方案**: Moonrepo Monorepo + FastAPI + Next.js + PostgreSQL  
**目标交付**: 完整的自主托管财务管理、复式记账与智能对账分析平台

***

## 目录

1. [项目概览](#1-项目概览)  
2. [技术栈与 Monorepo 方案](#2-技术栈与-monorepo-方案)  
3. [领域建模与复式记账设计](#3-领域建模与复式记账设计)  
4. [银行对账与智能匹配算法](#4-银行对账与智能匹配算法)  
5. [AI 能力：Gemini 3 Flash 集成](#5-ai-能力gemini-3-flash-集成)  
6. [Moonrepo 工作区结构与任务编排](#6-moonrepo-工作区结构与任务编排)  
7. [分阶段交付计划](#7-分阶段交付计划)  
8. [部署与运维](#8-部署与运维)  
9. [风险与缓解](#9-风险与缓解)  

***

## 1. 项目概览

### 1.1 项目目标

构建一个**面向个人/家庭资产负债管理的专业级系统**，以严谨的会计模型为核心，辅以 AI 能力进行文档提取与解释，而不是把 LLM 当作记账核心。

核心能力：

- ✅ **智能对账单导入**：PDF/CSV/XLSX 银行与券商对账单自动解析  
- ✅ **复式记账系统**：基于会计恒等式的总账与明细账设计  
- ✅ **银行对账引擎**：流水与总账之间的多维度匹配与自动对账  
- ✅ **财务报表生成**：资产负债表、利润表、现金流量表  
- ✅ **AI 财务解读**：基于 Gemini 3 Flash 的报表解读与趋势说明  
- ✅ **投资与多账户支持**：银行、信用卡、券商、房贷等多类账户  
- ✅ **完全自主托管**：自部署在 Dokploy / K3s 上，数据完全自管  

### 1.2 核心业务流程（自上而下）

1. 用户从银行/券商导出 PDF/CSV/XLSX 对账单  
2. 系统上传文件 → Gemini 3 Flash (Vision) 抽取结构化交易明细  
3. 系统验证期初/期末余额与流水总和的一致性  
4. 将对账单交易转化为候选**会计事件**与**分录**  
5. 对每条银行流水，使用多维度算法匹配现有或候选分录，给出匹配置信度  
6. 高置信度自动通过，中等置信度进入审核队列，低置信度保留为未匹配  
7. 审核通过的分录进入总账，系统持续生成报表与趋势分析  
8. AI 财务顾问基于报表与对账状态进行解释与问答  

### 1.3 关键指标

| 维度 | 目标 | 验收标准 |
|------|------|---------|
| **对账准确性** | ≥ 98% 自动匹配准确率 | 抽样人工核对 |
| **复式记账完整性** | 100% 分录平衡 | 任意时间点满足会计恒等式[1][2] |
| **性能** | p95 < 500ms | 压测结果 |
| **稳定性** | 99.5% 可用性 | 监控与告警 |
| **安全性** | 金融场景标准 | 加密、审计、最小权限 |
| **可用性** | 上手时间 < 30 分钟 | 用户访谈 |

***

## 2. 技术栈与 Monorepo 方案

### 2.1 Monorepo 平台：Moonrepo

从 NX 改为 **Moonrepo** 的理由：

- **多语言一等公民**：Moonrepo 的 task runner 对 Node.js 与其他语言（如 Python）的支持更中立，适合你 Python + TS 的组合场景。[3]
- **任务与缓存模型**：基于文件哈希和任务图的增量执行，比依赖 JS 生态的传统方案更轻量。[3]
- **项目粒度适配**：可以精确为 backend / frontend / infra / docs 定义不同任务与依赖图。  

Moonrepo 将统一规划：

- 后端：FastAPI + SQLAlchemy + Alembic + pytest  
- 前端：Next.js 14 (App Router) + React + Tailwind + shadcn/ui  
- AI：Gemini 3 Flash API 调用封装  
- Infra：Docker、Dokploy 部署脚本、定时任务、备份脚本  

### 2.2 完整技术栈

- **后端**  
  - FastAPI (Python 3.12) – 主 API 框架  
  - SQLAlchemy 2 + asyncpg – ORM 与异步数据库访问  
  - Alembic – 数据库迁移  
  - Pydantic v2 – 请求/响应与领域模型校验  
  - PostgreSQL 15 – 事务级数据库  
  - Redis 7 – 缓存与队列  
  - httpx / aiohttp – 调用 Gemini/Yahoo Finance 等 API  
  - structlog – 结构化日志  

- **前端**  
  - Next.js 14 (App Router) + React 18 + TypeScript  
  - TailwindCSS + shadcn/ui – 快速构建交互界面  
  - TanStack Query – 数据获取与缓存  
  - Zustand – 全局 UI 状态（过滤、选中等）  
  - Recharts / ECharts – 报表与趋势图表  

- **AI 与数据**  
  - Gemini 3 Flash (Vision + Text) – 文档提取 + 对话解释[4]
  - yfinance / 其他数据源 – 汇率和行情[4]

- **基础设施**  
  - Moonrepo – Monorepo 管理与任务编排[3]
  - Docker + docker-compose – 本地与测试环境  
  - Dokploy – 生产部署与运维  
  - SigNoz / OpenTelemetry – 监控与日志  

***

## 3. 领域建模与复式记账设计

### 3.1 会计恒等式与账户分类

系统的核心约束是会计恒等式：[1][2]

\[
资产 = 负债 + 权益
\]

引入收入与费用后转化为：

\[
资产 = 负债 + 权益 + (收入 - 费用)
\]

因此，账户类型划分为：

- **Asset**：银行账户、现金、投资、房产、应收账款  
- **Liability**：信用卡、房贷、其他借款  
- **Equity**：所有者权益、保留盈余  
- **Income**：工资、股息、利息收入  
- **Expense**：消费、手续费、利息支出  

每一个具体账户都挂在上述五大类之一，并有币种与属性（流动/非流动）。[2][1]

### 3.2 记账结构：凭证头与分录行

为了支持一对多、多对多的复杂业务，采用「**凭证头 + 分录行**」模型，而不是固定单条记录只有一个 debit 和 credit 字段。[1][2]

**JournalEntry（凭证头）**

- id  
- user_id  
- entry_date  
- source_type（bank_statement / manual / system_adjustment）  
- source_id（关联记录，如 BankStatementTransaction）  
- memo（摘要）  
- status（draft / posted / reconciled / void）  
- created_at / updated_at  

**JournalLine（分录行）**

- id  
- journal_entry_id  
- account_id  
- direction（DEBIT / CREDIT）  
- amount  
- currency  
- fx_rate（若与主账币种不同）  
- event_type（salary / card_payment / transfer / fee 等）  
- tags（JSONB）  

约束：

- 每个 JournalEntry 至少 2 条 JournalLine  
- 同一 JournalEntry 内，`sum(DEBIT.amount) == sum(CREDIT.amount)`  

这保证了只要 JournalEntry 处于 `posted` 状态，总账就满足会计恒等式。[2][1]

### 3.3 典型业务映射示例

1. **工资收入入账**

- 业务：雇主打入 5,000 SGD 到主银行账户  
- 分录：

  - 借：Asset – Bank: Main       5,000  
  - 贷：Income – Salary          5,000  

2. **信用卡消费自动入账**

- 业务：信用卡消费 200 SGD，稍后用银行账户还款  
- 消费记账（流水来自信用卡对账单）：

  - 借：Expense – Dining         200  
  - 贷：Liability – Credit Card  200  

- 还款记账（流水来自银行对账单）：

  - 借：Liability – Credit Card  200  
  - 贷：Asset – Bank: Main       200  

3. **跨币种投资买入**

- 业务：从 SGD 账户换成 USD 买股票  
- 可能拆成两步分录：  
  - 外汇兑换  
  - 股票买入  
- 日后报表基于 fx_rate 进行统一币种折算。[5][4]

***

## 4. 银行对账与智能匹配算法

### 4.1 对账目标

对账的目标是在「**银行/券商流水**」与「**总账分录**」之间建立强一致映射，使得：  

- 每笔流水都有对应的分录（或合理地聚合/拆分匹配）  
- 每笔分录都能追溯到某个流水或手工业务事件  
- 对账状态可视化（已匹配、部分匹配、未匹配）[6][5]

### 4.2 主要实体

- **BankStatementTransaction**  
  - id, account_id（对应银行账户）, txn_date, amount, direction（IN/OUT）, description, reference, currency, raw_line 等  

- **ReconciliationMatch**  
  - id  
  - bank_txn_id  
  - journal_entry_ids（可能一对多）  
  - match_score（0-100）  
  - status（auto_accepted / pending_review / rejected）  
  - breakdown（各评分维度的分值）  

### 4.3 多维度匹配评分模型

对每条银行流水 \( T \) 和候选总账分录组合 \( E \) 打分，综合考虑以下因素：[5][6][4]

1. **金额匹配（约 40% 权重）**  
   - 精确相等：100 分  
   - 容差内（考虑手续费，绝对值差异在阈值内）：90 分  
   - 多笔合计匹配：70 分  
   - 差异过大：低于 40 分  

2. **日期相近度（约 25% 权重）**  
   - 同日：100 分  
   - ±1–3 天：90 分  
   - ±4–7 天：70 分  
   - 超过一周：30 分及以下  

3. **描述相似度（约 20% 权重）**  
   - 使用字符串相似度算法（如编辑距离、token 相似）对比：  
     - 对方名称（MERCHANT NAME）  
     - 部分卡号/参考号  
     - 交易渠道（FAST/PAYNOW/VISA/MASTER 等）[7][4]

4. **账户类型与业务模式合理性（约 10% 权重）**  
   - 银行账户与收入 / 费用 / 负债组合必须符合常识（例如工资通常是 Bank + Income，信用卡还款是 Bank + Liability 等）。[8][2]

5. **历史模式与异常（约 5% 权重）**  
   - 对相同对手方、相似金额、固定周期的交易给予加分（订阅类）。[4]
   - 与以往模式差异极大的交易降分并标记为潜在异常。[5]

综合得分后按照阈值处理：

- **≥ 85**：自动接受，直接标记为已对账（同时写 ReconciliationMatch 和审计日志）。[6]
- **60–84**：进入审核队列，由用户确认或修改匹配。  
- **< 60**：标记为未匹配，需要用户手动创建或调整分录。  

### 4.4 对账流程

1. 导入对账单 → 写入 BankStatementTransaction  
2. 针对每条流水，找到候选总账分录组合（单笔、多笔）  
3. 计算匹配得分 + 各维度评分  
4. 依据阈值进行自动匹配或推入审核队列  
5. 用户在前端审核界面确认或修改  
6. 对已确认的匹配：  
   - 更新 JournalEntry 状态为 `reconciled`  
   - 更新 BankStatementTransaction 状态为 `matched`  

***

## 5. AI 能力：Gemini 3 Flash 集成

### 5.1 文档解析（Vision）

- 对 PDF/图片形式的对账单，使用 Gemini 3 Flash 的 Vision 能力抽取结构化信息，包括：  
  - 账户信息（银行名、账号后几位、币种）  
  - 账期（开始/结束日期，期初/期末余额）  
  - 交易明细（日期、金额、方向、描述、参考号）[4]

- 系统对提取结果进行：  
  - 余额验证：期初 + 流水合计 ≈ 期末  
  - 数据完整性检查：缺失字段、解析错误次数  
  - 不通过的文档标记为「需人工复核」，不进入自动匹配阶段。[4]

### 5.2 AI 财务顾问

- 输入：  
  - 资产负债表、利润表、现金流量表  
  - 对账状态（多少未匹配、异常交易数量）  
  - 用户提问（中文/英文）  

- 输出：  
  - 对当前资产结构的解读（如负债率、现金储备与固定支出的覆盖比例）[9][2]
  - 收入与支出趋势说明，以及注意事项  
  - 对异常交易或大额波动的解释建议  

AI 严格作为 **解释层和协助决策层**，不替代底层记账和对账算法，避免 LLM 误差直接污染账本。[4]

***

## 6. Moonrepo 工作区结构与任务编排

### 6.1 目录结构

```bash
financial-manager/
├── moon.yml                      # Workspace 配置
│
├── apps/
│   ├── backend/
│   │   ├── pyproject.toml
│   │   ├── moon.yml              # build/test/lint/migrate 等任务
│   │   └── src/app/
│   │       ├── routers/
│   │       ├── models/
│   │       ├── schemas/
│   │       ├── services/
│   │       │   ├── accounting.py         # 复式记账核心
│   │       │   ├── reconciliation.py      # 对账匹配算法
│   │       │   ├── extraction.py          # Gemini 解析
│   │       │   ├── confidence.py          # 置信度评分
│   │       │   └── anomaly_detection.py   # 异常检测
│   │       └── ...
│   │
│   └── frontend/
│       ├── package.json
│       ├── moon.yml
│       └── app/
│           ├── dashboard/
│           ├── reconciliation/
│           ├── upload/
│           └── chat/
│
├── packages/
│   ├── types/
│   └── shared-utils/
│
└── infra/
    ├── moon.yml
    ├── docker-compose.yml
    └── scripts/
        ├── migrate.sh
        ├── backup.sh
        └── restore.sh
```

### 6.2 典型 Moon 任务

- `backend:dev` – 启动 FastAPI 开发服务  
- `backend:test` – 运行 pytest（含数据库集成测试）  
- `backend:migrate` – Alembic 升级  
- `frontend:dev` – Next.js dev  
- `frontend:build` – Next.js 构建  
- `infra:docker:up` – 启动本地 docker-compose（Postgres + Redis + app）  

Moonrepo 会根据源代码改动自动决定需要执行哪些任务，减少不必要的 CI 开销。[3]

***

## 7. 分阶段交付计划

### Phase 0 – 基础设施与 Monorepo 搭建（1–2 周）

- 初始化 Moonrepo workspace  
- 搭建 backend / frontend / infra 目录与基础任务  
- docker-compose 本地环境（Postgres + Redis）  
- 健康检查接口 `/api/health` 与最小 UI  

### Phase 1 – 数据模型与复式记账核心（2–3 周）

- PostgreSQL Schema（用户、账户、科目、JournalEntry、JournalLine 等）[1][2]
- SQLAlchemy 模型与 Pydantic schema  
- 首批 API：账户管理、手工分录创建  
- 复式记账平衡验证逻辑与单元测试  

### Phase 2 – 对账单导入与解析（3–4 周）

- 文件上传 API + 前端拖拽上传界面  
- Gemini 3 Flash 文档解析管道[4]
- 期初/期末余额与流水总和校验  
- 将解析结果保存为 BankStatementTransaction  

### Phase 3 – 对账引擎与审核队列（3–4 周）

- 多维度匹配算法与置信度评分实现[6][5][4]
- ReconciliationMatch 模型与 API  
- 前端对账界面（流水列表 + 候选匹配 + 审核操作）  
- 自动匹配 / 人工复核流程打通  

### Phase 4 – 报表与 AI 解读（2–3 周）

- 资产负债表、利润表、现金流量表计算逻辑[10][2]
- 前端仪表板与图表  
- AI 财务顾问：基于报表与对账状态的解读对话[9][4]
- 性能优化与生产部署（Dokploy）  

***

## 8. 部署与运维

- 使用 Dokploy 管理 backend 与 frontend 容器，配置健康检查与自动重启  
- 数据库部署在单独的 PostgreSQL 实例，启用定期备份与 WAL 归档  
- Redis 主要用于缓存与队列，不作为持久存储  
- SigNoz / OpenTelemetry 收集：  
  - API 延迟、错误率  
  - 数据库查询耗时  
  - 对账任务执行时间与失败率[5]

***

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|---------|
| 文档解析错误污染账本 | 中 | 高 | 解析层与记账层严格解耦，所有导入必须通过余额校验与人工抽查[4][5] |
| 多币种处理与汇率偏差 | 中 | 中 | 统一折算策略，记录 fx_rate，允许报表重算与回溯[5][4] |
| 对账算法误匹配 | 中 | 中 | 多维度评分 + 阈值控制 + 审核队列，重要账户启用“自动匹配禁用”选项[6][5] |
| LLM 成本与速率限制 | 中 | 中 | 缓存文档解析结果，分批处理，必要时回落到本地解析逻辑[4] |
| Monorepo 复杂度 | 低 | 中 | 严格约定目录结构与任务命名，保持项目边界清晰[3] |

***

**文档版本**: v3.0 – Moonrepo + Gemini 3 Flash + 智能对账重设计  
**更新日期**: 2026-01-09  
**项目状态**: 架构定稿，可按 Phase 0 启动实现

[1](https://en.wikipedia.org/wiki/Double-entry_bookkeeping)
[2](https://www.myob.com/au/resources/guides/accounting/double-entry-accounting)
[3](https://moonrepo.dev/moon)
[4](https://blog.xero.com/product-updates/behind-the-tech-bank-rec-predictions/)
[5](https://optimus.tech/blog/mastering-bank-reconciliation-advanced-strategies-for-financial-practitioners)
[6](https://www.cashbook.com/auto-matching-algorithms-in-accounts-reconciliation/)
[7](https://www.linkedin.com/pulse/finally-automate-bank-reconciliation-ai-corporate-treasury-101-1e)
[8](https://www.moderntreasury.com/learn/single-vs-double-entry-accounting)
[9](https://www.salesforce.com/ap/blog/double-entry-accounting-and-bookkepping/)
[10](https://www.alaan.com/blog/gl-in-accounting-double-entry)