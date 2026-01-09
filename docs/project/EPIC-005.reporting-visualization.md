# EPIC-005: Financial Reports & Visualization

> **Status**: ⏳ Pending  
> **Phase**: 4  
> **Duration**: 3 周  
> **Dependencies**: EPIC-002 (可and EPIC-003/004 并行)  

---

## 🎯 Objective

生成标准财务三表 (资产负债表, 利润表, 现金流量表), 可视化资产结构and趋势, 帮助用户全面了解财务状况。

**核心约束**:
```
资产负债表: Assets = Liabilities + Equity
利润表: Net Income = Income - Expenses
Accounting equation验证: 报表Required符合Accounting equation
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | 报表准确性 | 三表Required符合会计准则, 数据来源可追溯 |
| 🏗️ **Architect** | 计算性能 | 大数据量报表需缓存or物化视图 |
| 💻 **Developer** | 图表实现 | Recharts 轻量场景, ECharts 复杂图表 |
| 📋 **PM** | 用户理解 | 报表需添加说明and示例, 非会计专业用户也能看懂 |
| 🧪 **Tester** | 计算验证 | and手工计算对比, 误差 < 1% |

---

## ✅ Task Checklist

### 报表计算 (Backend)

- [ ] `services/reporting.py` - 报表生成服务
  - [ ] `generate_balance_sheet()` - 资产负债表
    - 按账户类型聚合余额
    - 资产 = 负债 + 权益 验证
  - [ ] `generate_income_statement()` - 利润表
    - 收入/支出明细
    - 月度/季度/年度对比
  - [ ] `generate_cash_flow()` - 现金流量表 (P2)
    - 经营/投资/筹资活动分类
  - [ ] `get_account_trend()` - 账户趋势数据
  - [ ] `get_category_breakdown()` - 分类占比

### 多币种处理 (Backend)

- [ ] `services/fx.py` - 汇率服务
  - [ ] `get_exchange_rate()` - 获取汇率
  - [ ] `convert_to_base()` - 折算到本位币
  - [ ] 汇率缓存 (每日更新)
- [ ] 报表币种配置
  - [ ] 本位币设置 (default SGD)
  - [ ] 报表统一折算

### API 端点 (Backend)

- [ ] `GET /api/reports/balance-sheet` - 资产负债表
  - 参数: `as_of_date`, `currency`
- [ ] `GET /api/reports/income-statement` - 利润表
  - 参数: `start_date`, `end_date`, `currency`
- [ ] `GET /api/reports/cash-flow` - 现金流量表 (P2)
- [ ] `GET /api/reports/trend` - 趋势数据
  - 参数: `account_id`, `period` (daily/weekly/monthly)
- [ ] `GET /api/reports/breakdown` - 分类占比
  - 参数: `type` (income/expense), `period`
- [ ] `GET /api/reports/export` - 导出 Excel/CSV

### 仪表板 (Frontend)

- [ ] `/dashboard` - 首页仪表板
  - [ ] 资产总览卡片 (总资产, 总负债, 净资产)
  - [ ] 资产趋势折线图 (近 12 个月)
  - [ ] 收支对比柱状图 (月度)
  - [ ] 账户分布饼图 (按类型)
  - [ ] 最近交易列表
  - [ ] 未匹配提醒

### 报表页面 (Frontend)

- [ ] `/reports/balance-sheet` - 资产负债表
  - [ ] 三栏式布局 (资产 | 负债 | 权益)
  - [ ] 账户层级展开/折叠
  - [ ] 日期选择器
  - [ ] 导出按钮
- [ ] `/reports/income-statement` - 利润表
  - [ ] 收入/支出分类明细
  - [ ] 同比/环比对比
  - [ ] 时间范围选择
- [ ] `/reports/cash-flow` - 现金流量表 (P2)
- [ ] 筛选and交互
  - [ ] 日期范围
  - [ ] 账户类型
  - [ ] 币种切换
  - [ ] 标签筛选

### 图表组件 (Frontend)

- [ ] `components/charts/TrendChart.tsx` - 趋势图
- [ ] `components/charts/PieChart.tsx` - 饼图
- [ ] `components/charts/BarChart.tsx` - 柱状图
- [ ] `components/charts/SankeyChart.tsx` - 收支流向图 (P2)

---

## 📏 做得好不好 标准

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **资产负债表平衡** | Assets = Liabilities + Equity | 🔴 关键 |
| **利润表计算正确** | 手工验证 5 个月数据 | 🔴 关键 |
| **报表and分录一致** | 报表金额可追溯到分录 | 🔴 关键 |
| 报表生成时间 < 2s | 性能测试 (1 年数据) | Required |
| 移动端适配 | 响应式布局 | Required |
| 数据导出可用 | Excel/CSV 下载 | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| 报表缓存 (减少重复计算) | Redis 缓存命中 | ⏳ |
| 图表交互 (drill-down) | 点击查看明细 | ⏳ |
| 预算对比 | 实际 vs 预算 | ⏳ |
| 自定义报表 | 用户选择维度 | ⏳ |
| 定期报表邮件 | 自动发送月报 | ⏳ |

### 🚫 Not Acceptable Signals

- 资产负债表不平衡
- 报表金额and分录合计不一致
- 图表数据and报表数据不一致
- 性能超时 (> 10s)
- 移动端布局错乱

---

## 🧪 Test Scenarios

### 报表计算测试 (Required)

```python
def test_balance_sheet_equation():
    """资产负债表: Assets = Liabilities + Equity"""
    report = generate_balance_sheet(as_of_date=date(2025, 12, 31))
    assert abs(report.total_assets - (report.total_liabilities + report.total_equity)) < 0.01

def test_income_statement_calculation():
    """利润表: Net Income = Income - Expenses"""
    report = generate_income_statement(start=date(2025, 1, 1), end=date(2025, 12, 31))
    assert report.net_income == report.total_income - report.total_expenses

def test_report_matches_journal():
    """报表金额and分录合计一致"""
    # 手工计算某账户余额, and报表对比
```

### 多币种测试 (Required)

```python
def test_multi_currency_conversion():
    """多币种账户正确折算"""
    # SGD 账户 1000 + USD 账户 500 (汇率 1.35) = 1675 SGD

def test_fx_rate_update():
    """汇率更新后报表重算"""
```

### 性能测试 (Required)

```python
def test_report_generation_performance():
    """1 年数据报表生成 < 2s"""
    # 插入 1000 笔分录, 测试报表生成时间
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - 账户and分录表
- [reporting.md](../ssot/reporting.md) - 报表计算规则
- [market_data.md](../ssot/market_data.md) - 汇率数据源

---

## 🔗 Deliverables

- [ ] `apps/backend/src/services/reporting.py`
- [ ] `apps/backend/src/services/fx.py`
- [ ] `apps/backend/src/routers/reports.py`
- [ ] `apps/frontend/app/dashboard/page.tsx`
- [ ] `apps/frontend/app/reports/balance-sheet/page.tsx`
- [ ] `apps/frontend/app/reports/income-statement/page.tsx`
- [ ] `apps/frontend/components/charts/`
- [ ] 更新 `docs/ssot/reporting.md`

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| 现金流量表 | P2 | v1.5 |
| 报表物化视图 | P2 | 性能优化阶段 |
| 预算管理 | P3 | v2.0 |
| 自定义报表 | P3 | v2.0 |

---

## ❓ Q&A (Clarification Required)

### Q1: 报表期间定义
> **Question**: 利润表 "月度"如何定义？

**✅ Your Answer**: A - 自然月 (1-31), 最直观

**Decision**: 使用自然月
- 所有报表default按自然月分组 (1 月 1 日至 1 月 31 日)
- API 参数: `period_type` = "natural_month"
- 后续可扩展支持其他Duration (week, quarter, year)
- 数据库查询优化:按 `DATE_TRUNC('month', entry_date)` 分组

### Q2: 汇率数据源
> **Question**: 使用什么汇率数据源？

**✅ Your Answer**: B - Yahoo Finance API (免费)

**Decision**: 使用 Yahoo Finance 作为汇率源
- 集成 yfinance 库or直接Call Yahoo Finance API
- 支持 货币对:SGD/USD, SGD/CNY, SGD/HKD 等 (通过 Forex 数据)
- 缓存策略:
  - 每日更新一次汇率 (早上 UTC 9:00)
  - Redis 缓存 24 小时
  - 支持手动刷新按钮
- 汇率历史:
  - 记录每日汇率到 `ExchangeRate` 表
  - 格式: `date, from_currency, to_currency, rate`
- 降级方案:
  - 如果 Yahoo Finance 不可用, 使用上次缓存汇率
  - 如果无缓存, 提示用户手动设置

### Q3: 历史汇率处理
> **Question**: 历史交易使用当时汇率还是当前汇率折算？

**✅ Your Answer**: A - 使用交易日汇率 (记录在分录中, 符合会计准则)

**Decision**: 历史汇率记录在分录
- JournalLine   `fx_rate` field记录交易日 汇率
- 分录创建时, 自动查询当日汇率并存储
- 报表计算时使用分录中  fx_rate, 不查实时汇率
- 好处:
  - ✅ 符合 GAAP 准则 (交易日原则)
  - ✅ 报表可回溯 (修改汇率不Impact历史报表)
  - ✅ 可追溯汇兑损益
- 汇兑损益计算:
  - 原币金额 × 交易日汇率 = 本位币余额 (记账时)
  - 原币金额 × 报表日汇率 = 报表日折算值
  - 差额 = 汇兑损益 (Forex Gain/Loss)

### Q4: 图表库选择
> **Question**: 使用 Recharts 还是 ECharts？

**✅ Your Answer**: B - 仅 ECharts, 因为需要 K 线图等金融图表

**Decision**: 统一使用 ECharts
- ECharts 提供丰富 金融图表:K 线, Candlestick, Volume 等
- 应用场景:
  - 资产趋势:K 线图 (显示开盘, 收盘, 最高, 最低)
  - 收支分析:柱状图, 折线图
  - 资产分布:饼图, Sunburst 图
  - 现金流:Sankey 图 (收支流向)
- 优化:
  - 按需加载 ECharts  子模块 (减少 bundle 大小)
  - 使用 Canvas 渲染大数据量图表 (性能优化)
- 依赖:`echarts`, `echarts-for-react` (React wrapper)

### Q5: 报表导出格式
> **Question**: 需要支持哪些导出格式？

**✅ Your Answer**: CSV 作为中间产物 (数据导出), PDF 作为最终报表 (演示用)

**Decision**: 多格式导出策略
- **CSV** (中间产物 - 数据导出):
  - 用于数据分析, 二次加工
  - 包含完整field:账户, 金额, 日期, 备注, 标签等
  - 支持导出范围筛选 (日期, 账户, 类型)
  - 示例:`accounts_export_2025_01.csv`, `transactions_export_2025_01.csv`
  
- **PDF** (最终报表 - 演示用):
  - 使用 ReportLab or WeasyPrint 库生成
  - 包含:资产负债表, 利润表, 汇总图表
  - 专业排版:公司名, 日期, 签名线等
  - 嵌入图表 (静态图片)
  - 示例:`Financial_Report_2025_01.pdf`
  
- **Excel** (可选, 后续迭代):
  - 暂不实现 (v1.0 不提供)
  - 如需要可在 v1.5+ 添加

- **导出 API**:
  - `GET /api/reports/balance-sheet/export?format=pdf`
  - `GET /api/reports/transactions/export?format=csv`
  - 后端动态生成文件, 返回下载链接 (or流式下载)

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | 报表计算逻辑 + API | 16h |
| Week 2 | 仪表板 + 图表组件 | 20h |
| Week 3 | 报表页面 + 导出 + 测试 | 16h |

**总预计**: 52 小时 (3 周)

**注意**: 本 EPIC 可在 EPIC-002 完成后启动, and EPIC-003/004 并行开发。
