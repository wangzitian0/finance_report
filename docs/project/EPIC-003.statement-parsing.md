# EPIC-003: Smart Statement Parsing

> **Status**: ⏳ Pending  
> **Phase**: 2  
> **Duration**: 4 weeks  
> **Dependencies**: EPIC-002  

---

## 🎯 Objective

使用 Gemini 3 Flash Vision 解析银行/券商对账单, 自动提取交易明细并生成候选分录。

**核心流程**:
```
Upload → Gemini Vision → JSON → Validation → BankStatementTransaction → 候选 JournalEntry
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | 解耦设计 | AI 只做解析, 不直接写入账本, 通过验证层过滤错误 |
| 💻 **Developer** | API 集成 | Gemini 3 Flash Call封装, 含重试, 降级, 成本控制 |
| 📊 **Accountant** | 数据完整性 | 期初 + 流水 ≈ 期末, 验证不通过则拒绝入库 |
| 🔗 **Reconciler** | 下游依赖 | 解析结果Required结构化, 方便后续匹配算法使用 |
| 🧪 **Tester** | 解析准确率 | 多银行, 多格式覆盖测试, 目标 ≥ 95% |
| 📋 **PM** | 用户体验 | 拖拽上传, 解析进度, 错误提示友好 |

---

## ✅ Task Checklist

### Data Model (Backend)

- [ ] `BankStatement` model - 对账单头 (account_id, period, opening/closing_balance)
- [ ] `BankStatementTransaction` model - 交易明细 (txn_date, amount, direction, description)
- [ ] Alembic 迁移脚本
- [ ] Pydantic Schema

### Gemini 集成 (Backend)

- [ ] `services/extraction.py` - 文档解析服务
  - [ ] `parse_pdf()` - PDF 解析 (Vision API)
  - [ ] `parse_csv()` - CSV 解析 (规则 + AI 辅助)
  - [ ] `parse_xlsx()` - Excel 解析
- [ ] Prompt 模板管理
  - [ ] DBS/POSB 对账单模板
  - [ ] OCBC 对账单模板
  - [ ] 信用卡账单通用模板
- [ ] 解析结果结构化
  ```python
  class ParsedStatement:
      bank_name: str
      account_number: str  # 后4位
      period_start: date
      period_end: date
      opening_balance: Decimal
      closing_balance: Decimal
      transactions: list[ParsedTransaction]
  ```

### 验证层 (Backend)

- [ ] `services/validation.py` - 验证服务
  - [ ] `validate_balance()` - 期初 + 流水 ≈ 期末 (容差 0.1 USD)
  - [ ] `validate_completeness()` - 必填field检查
  - [ ] `detect_duplicates()` - 重复导入检测
- [ ] 验证失败处理
  - [ ] 标记为 "需人工复核"
  - [ ] 记录失败原因
  - [ ] 通知用户

### API 端点 (Backend)

- [ ] `POST /api/statements/upload` - 文件上传
- [ ] `GET /api/statements` - 对账单列表
- [ ] `GET /api/statements/{id}` - 对账单详情 (含交易明细)
- [ ] `POST /api/statements/{id}/approve` - 确认对账单
- [ ] `POST /api/statements/{id}/reject` - 拒绝对账单
- [ ] `GET /api/statements/{id}/transactions` - 交易明细列表

### 前端界面 (Frontend)

- [ ] `/upload` - 上传页面
  - [ ] 拖拽上传组件
  - [ ] 文件类型/大小验证
  - [ ] 上传进度条
  - [ ] 解析状态轮询
- [ ] `/statements` - 对账单管理
  - [ ] 对账单列表 (状态标签)
  - [ ] 对账单详情 (交易明细表格)
  - [ ] 解析结果预览
  - [ ] 确认/拒绝操作
- [ ] 错误处理
  - [ ] 解析失败提示
  - [ ] 验证失败详情
  - [ ] 重试入口

---

## 📏 做得好不好 标准

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **解析成功率 ≥ 95%** | 10 份真实对账单测试 | 🔴 关键 |
| **余额验证 100% 执行** | 期初+流水≈期末检查 | 🔴 关键 |
| **解析错误不入库** | 验证失败返回错误 | 🔴 关键 |
| 支持 PDF 格式 (DBS, OCBC) | 银行样本测试 | Required |
| 支持 CSV 通用格式 | 标准 CSV 测试 | Required |
| 文件大小限制 10MB | 上传验证 | Required |
| 解析时间 < 30s | 性能测试 | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| 支持 XLSX 格式 | Excel 样本测试 | ⏳ |
| 解析结果可编辑 | 前端表格编辑 | ⏳ |
| 批量上传 | 多文件队列处理 | ⏳ |
| 解析缓存 | 相同文件不重复Call API | ⏳ |
| Gemini 成本报告 | Token 使用统计 | ⏳ |

### 🚫 Not Acceptable Signals

- 解析成功率 < 90%
- 余额验证被跳过
- 解析错误数据进入账本
- Gemini API 频繁超时
- 用户无法理解错误原因

---

## 🧪 Test Scenarios

### Unit tests (Required)

```python
# 余额验证
def test_balance_validation_passes():
    """期初 1000 + 流水 500 - 300 = 期末 1200"""

def test_balance_validation_fails():
    """期初 1000 + 流水 500 ≠ 期末 1600"""

# 解析结果
def test_parse_dbs_pdf():
    """DBS 对账单解析, field完整"""

def test_parse_invalid_pdf():
    """非对账单 PDF 应返回解析失败"""
```

### Integration tests (Required)

```python
def test_upload_and_parse_flow():
    """完整上传→解析→验证→入库流程"""

def test_duplicate_upload_detection():
    """重复上传同一文件应提示"""

def test_gemini_retry_on_timeout():
    """Gemini 超时应自动重试"""
```

### 样本覆盖 (Required)

| 银行 | 格式 | 样本数 | 预期准确率 |
|------|------|--------|------------|
| DBS/POSB | PDF | 3 | ≥ 95% |
| OCBC | PDF | 2 | ≥ 95% |
| 信用卡 | PDF | 3 | ≥ 90% |
| 通用 | CSV | 2 | ≥ 98% |

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - BankStatement/BankStatementTransaction 表
- [extraction.md](../ssot/extraction.md) - 解析规则and Prompt 设计

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/statement.py`
- [ ] `apps/backend/src/services/extraction.py`
- [ ] `apps/backend/src/services/validation.py`
- [ ] `apps/backend/src/routers/statements.py`
- [ ] `apps/frontend/app/upload/page.tsx`
- [ ] `apps/frontend/app/statements/page.tsx`
- [ ] 更新 `docs/ssot/extraction.md` (Prompt 模板)
- [ ] 测试样本集 `tests/fixtures/statements/`

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| 本地 PDF 解析降级 | P2 | 后续迭代 |
| 更多银行支持 (UOB, Citi) | P3 | 后续迭代 |
| OCR 预处理 (扫描件) | P3 | 后续迭代 |

---

## ❓ Q&A (Clarification Required)

### Q5: 支持 银行Priority
> **Question**: 第一版需要支持哪些银行 对账单？

**✅ Your Answer**: DBS + 招商银行 + Maybank + Wise, 还需支持券商, 保险等各种机构。采用通用结构 + 灵活扩展field 设计。

**Decision**: 采用高度可扩展 对账单model
- **核心field** (所有对账单统一):
  - `period_start`, `period_end`, `opening_balance`, `closing_balance`
  - `transactions[]` 包含标准化field: `txn_date`, `amount`, `direction`, `description`
- **扩展field** (JSONB):
  - `bank_specific_data`: 银行特有field (如参考号, 交易码等)
  - `institution_type`: 标记机构类型 (bank, brokerage, insurance, wallet 等)
  - `custom_fields`: 用户可添加 自定义field
- **Prompt 模板**按机构类型分组:
  - `templates/dbs.yaml`
  - `templates/ocbc.yaml`
  - `templates/citic.yaml`
  - `templates/brokerage_generic.yaml`
  - `templates/insurance_generic.yaml`
  - `templates/fintech_generic.yaml` (Wise, Revolut 等)
- **机构库维护**:
  - 前端提供机构/账户类型选择器
  - 用户可为新机构配置 Prompt 模板
  - 社区贡献模板库

### Q6: Gemini API 成本控制
> **Question**: 如何控制 Gemini API Call成本？

**✅ Your Answer**: 使用 OpenRouter, 每天 $2 限制已在 API 层面, 应用层无需额外限制

**Decision**: 应用层依赖 OpenRouter  官方限制
- Call Gemini 3 Flash 通过 OpenRouter (非直接 Google API)
- OpenRouter 有每日配额管理, 超限自动返回 429 错误
- 应用层无需实现Call限制, 但需优雅处理 API 配额耗尽情况
- 当 OpenRouter 返回配额不足时, 降级到本地规则解析or提示用户
- 环境变量: `OPENROUTER_API_KEY`, `OPENROUTER_DAILY_LIMIT_USD=2`

### Q7: 解析失败 处理方式
> **Question**: 解析失败时用户可以做什么？

**✅ Your Answer**: C - 支持重试 + 人工编辑。重试时优先升级到更强 model。

**Decision**: 分层降级策略, 提升解析成功率
- **第 1 层**: Gemini 3 Flash (快速, 便宜)
- **第 2 层**: 重试时升级到 Gemini 2.0 or更强model (通过 OpenRouter 可用)
- **第 3 层**: 显示部分解析结果, 允许用户编辑补充
- **第 4 层**: 手动录入 (完整表单)
- 流程:
  ```
  Upload PDF
  ├─ Try Gemini 3 Flash
  │  ├─ ✅ Success → Show results
  │  └─ ❌ Fail → Offer "Retry with stronger model"
  │     ├─ Try Gemini 2.0 / GPT-4
  │     ├─ ✅ Success → Show results
  │     └─ ❌ Fail → Show partial results + Edit form
  └─ User can always manually add/edit transactions
  ```
- 环境变量: `PRIMARY_MODEL=gemini-3-flash`, `FALLBACK_MODELS=["gemini-2.0", "gpt-4-turbo"]`
- UI 展示重试进度and当前使用 model

### Q8: 对账单账户关联
> **Question**: 上传对账单时如何关联到具体账户？

**✅ Your Answer**: C - 先解析再确认, AI Recommended关联账户, 用户确认

**Decision**: 两步流程 - 解析 + 确认关联
- 上传时用户可选择账户 (可选), or留空让 AI 推荐
- 解析后, 提取对账单中 账户信息 (银行名, 账号后 4 位, 币种等)
- 基于提取信息, 在系统中查找匹配  Account
  - 精确匹配: 账号后 4 位 + 币种Complete一致
  - 模糊匹配: 银行名 + 币种相同 账户
- 前端确认页面显示:
  - 解析出 账户信息 (银行, 账号尾号, 开户人等)
  - 系统推荐 账户 (带匹配信度标记)
  - 用户可选择推荐账户or手动选择
  - "创建新账户"入口 (如推荐账户不存在)

### Q9: 历史对账单导入
> **Question**: 是否需要支持批量导入历史对账单？

**✅ Your Answer**: C - 支持批量上传 + 异步队列处理。每个上传对应一个独立  ETL 任务。

**Decision**: 异步 ETL 任务队列架构
- **上传阶段**:
  - 支持多文件同时拖拽 (or zip)上传
  - 每个文件立即创建一条 `StatementProcessingTask` 记录
  - 返回任务 ID 列表and任务队列链接给用户
- **任务结构**:
  ```python
  class StatementProcessingTask:
      id: UUID
      file_name: str
      file_size: int
      upload_at: datetime
      status: Enum  # pending/processing/completed/failed
      progress: int  # 0-100
      error_message: Optional[str]
      extracted_data: Optional[dict]
      account_id: Optional[UUID]
  ```
- **处理流程** (独立任务):
  1. 上传文件到临时存储
  2. 异步工作进程拉取任务 (status=pending)
  3. Call Gemini 解析 (记录进度)
  4. 验证余额 (期初+流水≈期末)
  5. 存储 BankStatementTransaction
  6. 更新任务状态为 completed/failed
- **队列实现**:
  - 使用 Redis queue or Celery (取决于部署环境)
  - 支持任务Priority (单个文件Priority最高)
  - 任务重试策略 (失败自动重试 3 次)
- **UI**:
  - 上传后跳转到"任务队列"页面
  - 显示每个任务 进度条, 状态, 错误信息
  - 支持取消待处理任务
  - 完成后自动刷新对账单列表

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + Gemini integration | 16h |
| Week 2 | Validation layer + API + Prompt tuning | 20h |
| Week 3 | Frontend UI + Multi-bank testing | 16h |
| Week 4 | ETL queue + Layered retry + Integration | 16h |

**Total estimate**: 68 hours (4 weeks)
