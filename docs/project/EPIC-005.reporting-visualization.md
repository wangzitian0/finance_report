# EPIC-005: 财务报表与可视化

> **Status**: ⏳ Pending  
> **Phase**: 4  
> **周期**: 3 周  
> **依赖**: EPIC-002 (可与 EPIC-003/004 并行)  

---

## 🎯 目标

生成标准财务三表（资产负债表、利润表、现金流量表），可视化资产结构与趋势，帮助用户全面了解财务状况。

**核心约束**:
```
资产负债表: Assets = Liabilities + Equity
利润表: Net Income = Income - Expenses
会计恒等式验证: 报表必须符合会计恒等式
```

---

## 👥 角色审议

| 角色 | 关注点 | 审议意见 |
|------|--------|----------|
| 📊 **Accountant** | 报表准确性 | 三表必须符合会计准则，数据来源可追溯 |
| 🏗️ **Architect** | 计算性能 | 大数据量报表需缓存或物化视图 |
| 💻 **Developer** | 图表实现 | Recharts 轻量场景，ECharts 复杂图表 |
| 📋 **PM** | 用户理解 | 报表需添加说明和示例，非会计专业用户也能看懂 |
| 🧪 **Tester** | 计算验证 | 与手工计算对比，误差 < 1% |

---

## ✅ 任务清单

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
  - [ ] 汇率缓存（每日更新）
- [ ] 报表币种配置
  - [ ] 本位币设置（默认 SGD）
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
  - [ ] 资产总览卡片（总资产、总负债、净资产）
  - [ ] 资产趋势折线图（近 12 个月）
  - [ ] 收支对比柱状图（月度）
  - [ ] 账户分布饼图（按类型）
  - [ ] 最近交易列表
  - [ ] 未匹配提醒

### 报表页面 (Frontend)

- [ ] `/reports/balance-sheet` - 资产负债表
  - [ ] 三栏式布局（资产 | 负债 | 权益）
  - [ ] 账户层级展开/折叠
  - [ ] 日期选择器
  - [ ] 导出按钮
- [ ] `/reports/income-statement` - 利润表
  - [ ] 收入/支出分类明细
  - [ ] 同比/环比对比
  - [ ] 时间范围选择
- [ ] `/reports/cash-flow` - 现金流量表 (P2)
- [ ] 筛选与交互
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

## 📏 做得好不好的标准

### 🟢 合格标准 (Must Have)

| 标准 | 验证方法 | 权重 |
|------|----------|------|
| **资产负债表平衡** | Assets = Liabilities + Equity | 🔴 关键 |
| **利润表计算正确** | 手工验证 5 个月数据 | 🔴 关键 |
| **报表与分录一致** | 报表金额可追溯到分录 | 🔴 关键 |
| 报表生成时间 < 2s | 性能测试（1 年数据） | 必须 |
| 移动端适配 | 响应式布局 | 必须 |
| 数据导出可用 | Excel/CSV 下载 | 必须 |

### 🌟 优秀标准 (Nice to Have)

| 标准 | 验证方法 | 状态 |
|------|----------|------|
| 报表缓存（减少重复计算） | Redis 缓存命中 | ⏳ |
| 图表交互（drill-down） | 点击查看明细 | ⏳ |
| 预算对比 | 实际 vs 预算 | ⏳ |
| 自定义报表 | 用户选择维度 | ⏳ |
| 定期报表邮件 | 自动发送月报 | ⏳ |

### 🚫 不合格信号

- 资产负债表不平衡
- 报表金额与分录合计不一致
- 图表数据与报表数据不一致
- 性能超时（> 10s）
- 移动端布局错乱

---

## 🧪 测试场景

### 报表计算测试 (必须)

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
    """报表金额与分录合计一致"""
    # 手工计算某账户余额，与报表对比
```

### 多币种测试 (必须)

```python
def test_multi_currency_conversion():
    """多币种账户正确折算"""
    # SGD 账户 1000 + USD 账户 500 (汇率 1.35) = 1675 SGD

def test_fx_rate_update():
    """汇率更新后报表重算"""
```

### 性能测试 (必须)

```python
def test_report_generation_performance():
    """1 年数据报表生成 < 2s"""
    # 插入 1000 笔分录，测试报表生成时间
```

---

## 📚 SSOT 引用

- [schema.md](../ssot/schema.md) - 账户与分录表
- [reporting.md](../ssot/reporting.md) - 报表计算规则
- [market_data.md](../ssot/market_data.md) - 汇率数据源

---

## 🔗 交付物

- [ ] `apps/backend/src/services/reporting.py`
- [ ] `apps/backend/src/services/fx.py`
- [ ] `apps/backend/src/routers/reports.py`
- [ ] `apps/frontend/app/dashboard/page.tsx`
- [ ] `apps/frontend/app/reports/balance-sheet/page.tsx`
- [ ] `apps/frontend/app/reports/income-statement/page.tsx`
- [ ] `apps/frontend/components/charts/`
- [ ] 更新 `docs/ssot/reporting.md`

---

## 📝 技术债务

| 项目 | 优先级 | 计划解决时间 |
|------|--------|--------------|
| 现金流量表 | P2 | v1.5 |
| 报表物化视图 | P2 | 性能优化阶段 |
| 预算管理 | P3 | v2.0 |
| 自定义报表 | P3 | v2.0 |

---

## ❓ Q&A (待确认问题)

### Q1: 报表期间定义
> **问题**: 利润表的"月度"如何定义？  
> **选项**:
> - A) 自然月 (1-31)
> - B) 用户自定义起始日（如每月 25 日）
> - C) 基于账户设置（不同账户不同周期）
>
> **影响**: 影响日期筛选逻辑  
> **建议**: 选择 A，自然月最直观

**你的回答**: _________________

### Q2: 汇率数据源
> **问题**: 使用什么汇率数据源？  
> **选项**:
> - A) 固定汇率（用户手动设置）
> - B) Yahoo Finance API（免费）
> - C) 专业外汇 API（付费）
>
> **影响**: 影响成本和准确性  
> **建议**: 选择 B，个人使用精度足够

**你的回答**: _________________

### Q3: 历史汇率处理
> **问题**: 历史交易使用当时汇率还是当前汇率折算？  
> **选项**:
> - A) 使用交易日汇率（记录在分录中）
> - B) 使用报表日汇率统一折算
> - C) 支持两种模式切换
>
> **影响**: 影响汇率存储和报表计算  
> **建议**: 选择 A，更符合会计准则

**你的回答**: _________________

### Q4: 图表库选择
> **问题**: 使用 Recharts 还是 ECharts？  
> **选项**:
> - A) 仅 Recharts（轻量）
> - B) 仅 ECharts（功能强）
> - C) 混用（简单图用 Recharts，复杂图用 ECharts）
>
> **影响**: 影响开发复杂度和 bundle 大小  
> **建议**: 选择 A，第一版用 Recharts 足够

**你的回答**: _________________

### Q5: 报表导出格式
> **问题**: 需要支持哪些导出格式？  
> **选项**:
> - A) 仅 CSV
> - B) CSV + Excel
> - C) CSV + Excel + PDF
>
> **影响**: 影响后端库依赖  
> **建议**: 选择 B，Excel 满足大多数需求

**你的回答**: _________________

---

## 📅 时间线

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| Week 1 | 报表计算逻辑 + API | 16h |
| Week 2 | 仪表板 + 图表组件 | 20h |
| Week 3 | 报表页面 + 导出 + 测试 | 16h |

**总预计**: 52 小时 (3 周)

**注意**: 本 EPIC 可在 EPIC-002 完成后启动，与 EPIC-003/004 并行开发。
