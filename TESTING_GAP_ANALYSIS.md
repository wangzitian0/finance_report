# Testing Gap Analysis & E2E Strategy

## 问题：为什么测试没有发现 `primary_model` 的变更？

### 根本原因分析

**失败的测试**:
```python
# apps/backend/tests/test_main.py:284
def test_config_defaults(self):
    settings = Settings()
    assert settings.primary_model == "google/gemini-2.0-flash-exp:free"  # ❌ 硬编码旧值
```

**问题**:
1. ✅ **有单元测试** - 测试存在
2. ❌ **硬编码期望值** - 测试断言写死了具体的模型名称
3. ❌ **缺少契约测试** - 没有测试"配置变更→测试更新"的一致性
4. ❌ **没有端到端验证** - 无法验证实际运行时配置是否正确

---

## 当前测试覆盖情况

### 1. 单元测试 (Unit Tests) ✅ 96%

| 层级 | 覆盖率 | 测试数量 | 说明 |
|------|--------|----------|------|
| Models | 100% | ~50 | SQLAlchemy 模型 |
| Services | 95% | ~200 | 业务逻辑 |
| Routers | 98% | ~150 | API 端点 |
| Schemas | 100% | ~30 | Pydantic 验证 |

**优点**:
- ✅ 高覆盖率（96.26%）
- ✅ 快速执行（5-6 分钟）
- ✅ 自动化 DB 生命周期管理

**缺点**:
- ❌ **测试与配置耦合** - 硬编码期望值
- ❌ **无法发现配置漂移** - 代码改了，测试没改
- ❌ **缺少跨层验证** - 只测单个组件

---

### 2. 集成测试 (Integration Tests) ⚠️ 有限

**现有集成测试** (2个文件):
```python
# apps/backend/tests/test_upload_integration.py
# - 测试：上传 → 存储 → 数据库 完整流程
# - 覆盖：Statements 上传 E2E 流程

# apps/backend/tests/test_accounting_integration.py  
# - 测试：创建账户 → 记账 → 统计报表
# - 覆盖：Journal Entries 完整生命周期
```

**缺失的集成测试**:
- ❌ **AI 模型调用集成** - 没有测试实际调用 OpenRouter
- ❌ **配置加载集成** - 没有测试 `.env` → `config.py` → 运行时
- ❌ **前后端集成** - 没有测试 API 契约一致性

---

### 3. 端到端测试 (E2E Tests) ❌ 缺失

**Smoke Tests 存在，但不足**:
```bash
# scripts/smoke_test.sh
# ✅ 测试页面可访问性
# ✅ 测试 /api/health
# ✅ 测试 CORS
# ❌ 不测试实际功能流程
# ❌ 不测试 AI 模型是否真的可用
```

**缺失的 E2E 场景**:
1. ❌ 用户上传 PDF → AI 解析 → 返回交易数据
2. ❌ 用户选择模型 → 调用成功/失败处理
3. ❌ localStorage 模型验证 → Fallback 流程
4. ❌ 多货币场景完整流程

---

## 测试金字塔现状 vs 理想

### 当前状态 (不平衡)

```
      E2E (0%)          ← ❌ 缺失
     /              \
   Integration (3%)    ← ⚠️ 不足
  /                  \
Unit Tests (96%)       ← ✅ 良好
```

### 理想状态

```
      E2E (5-10%)       ← 关键路径
     /              \
   Integration (20%)   ← 跨组件交互
  /                  \
Unit Tests (70-75%)    ← 快速反馈
```

---

## 具体改进建议

### 短期 (1-2 周)

#### 1. 修复配置测试的脆弱性

**问题**: `test_config_defaults` 硬编码期望值

**方案 A: 环境变量驱动** (推荐)
```python
# apps/backend/tests/test_main.py
def test_config_defaults(self):
    """Test Settings has reasonable defaults."""
    from src.config import Settings
    
    settings = Settings()
    # ✅ 从 .env.example 读取期望值，或使用合理的断言
    assert settings.primary_model.startswith("google/gemini")  # 宽松断言
    assert "gemini" in settings.primary_model.lower()
    assert settings.s3_bucket == "statements"
```

**方案 B: 契约测试**
```python
# apps/backend/tests/test_config_contract.py
import re

def test_config_primary_model_contract():
    """Ensure primary_model follows expected pattern."""
    from src.config import Settings
    
    settings = Settings()
    # ✅ 测试契约，而非具体值
    assert re.match(r'^google/gemini-\d+\.\d+-.*$', settings.primary_model), \
        f"Invalid model format: {settings.primary_model}"
    
def test_config_sync_with_env_example():
    """Ensure config.py default matches .env.example."""
    import os
    from pathlib import Path
    from src.config import Settings
    
    settings = Settings()
    env_example = Path(".env.example").read_text()
    
    # 从 .env.example 解析 PRIMARY_MODEL 的默认值
    match = re.search(r'^PRIMARY_MODEL=(.*)$', env_example, re.MULTILINE)
    if match:
        expected = match.group(1).strip()
        assert settings.primary_model == expected, \
            f"config.py default ({settings.primary_model}) != .env.example ({expected})"
```

#### 2. 添加 AI 模型调用集成测试

**问题**: 没有测试实际调用 OpenRouter 是否成功

**方案**: Mock + Real Call 混合
```python
# apps/backend/tests/test_ai_models_integration.py
import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.integration
async def test_get_models_from_openrouter():
    """Test fetching models from OpenRouter (real call)."""
    from src.services.openrouter_models import get_models
    
    models = await get_models()
    assert len(models) > 0
    assert any("gemini" in m["id"].lower() for m in models)

@pytest.mark.integration
async def test_primary_model_exists_in_catalog():
    """Test that config.PRIMARY_MODEL exists in OpenRouter catalog."""
    from src.config import settings
    from src.services.openrouter_models import get_models
    
    models = await get_models()
    model_ids = [m["id"] for m in models]
    
    assert settings.primary_model in model_ids, \
        f"PRIMARY_MODEL '{settings.primary_model}' not found in OpenRouter catalog"

@pytest.mark.integration  
async def test_invalid_model_raises_400(client, test_user):
    """Test uploading with invalid model returns 400."""
    response = await client.post(
        "/api/statements/upload",
        headers={"X-User-Id": str(test_user.id)},
        data={"model": "invalid-model-id"},
        files={"file": ("test.pdf", b"dummy", "application/pdf")}
    )
    assert response.status_code == 400
    assert "Invalid model" in response.json()["detail"]
```

#### 3. 添加前端模型验证集成测试

**问题**: 没有测试 localStorage 验证逻辑

**方案**: Playwright E2E 测试
```python
# apps/frontend/tests/e2e/test_model_validation.py
import pytest
from playwright.async_api import async_playwright

@pytest.mark.e2e
async def test_stale_model_id_auto_cleanup():
    """Test that stale localStorage model IDs are auto-cleared."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 1. Inject stale model ID
        await page.goto("http://localhost:3000/statements")
        await page.evaluate(
            'localStorage.setItem("statement_model_v1", "google/gemini-2.0-flash-thinking")'
        )
        
        # 2. Reload page
        await page.reload()
        await page.wait_for_selector('[data-testid="model-selector"]')
        
        # 3. Verify auto-cleanup
        stored = await page.evaluate('localStorage.getItem("statement_model_v1")')
        assert stored is None or stored != "google/gemini-2.0-flash-thinking", \
            "Stale model ID was not cleared"
        
        # 4. Verify fallback to default
        selected = await page.locator('[data-testid="model-selector"]').input_value()
        assert "gemini-3-flash-preview" in selected
        
        await browser.close()
```

---

### 中期 (1-2 月)

#### 4. 建立 E2E 测试套件

**目标**: 覆盖 5 个关键用户旅程

**工具选择**: Playwright (已经在用 pytest-playwright)

**关键场景**:

1. **Statement Upload E2E**
```python
# tests/e2e/test_statement_upload_e2e.py
@pytest.mark.e2e
async def test_upload_pdf_statement_full_flow():
    """
    E2E: 用户上传 PDF → AI 解析 → 查看交易 → 审批
    """
    # 1. Login
    # 2. Navigate to /statements
    # 3. Upload PDF file
    # 4. Wait for parsing (check progress)
    # 5. View extracted transactions
    # 6. Approve/Reject
    # 7. Verify in journal
```

2. **Model Selection E2E**
```python
@pytest.mark.e2e
async def test_model_selection_and_upload():
    """
    E2E: 用户选择不同模型 → 上传 → 验证调用正确模型
    """
    # 1. Navigate to /statements
    # 2. Select Gemini 3 from dropdown
    # 3. Upload file
    # 4. Verify backend logs show correct model
```

3. **Reconciliation E2E**
```python
@pytest.mark.e2e
async def test_reconciliation_full_flow():
    """
    E2E: 上传账单 → 自动对账 → 审核队列 → 批准
    """
    # 1. Upload bank statement
    # 2. Create manual journal entries
    # 3. Run reconciliation
    # 4. Check pending review queue
    # 5. Approve matches
```

4. **Multi-Currency E2E**
```python
@pytest.mark.e2e
async def test_multi_currency_reporting():
    """
    E2E: 多货币账户 → 交易 → 报表生成
    """
    # 1. Create USD account
    # 2. Create SGD account
    # 3. Add transactions
    # 4. Generate balance sheet (SGD)
    # 5. Verify FX conversion
```

5. **Error Handling E2E**
```python
@pytest.mark.e2e
async def test_openrouter_failure_handling():
    """
    E2E: OpenRouter 失败 → 显示错误 → Fallback 模型
    """
    # 1. Mock OpenRouter 503
    # 2. Upload statement
    # 3. Verify user sees error message
    # 4. Verify fallback model attempted
```

---

#### 5. 添加 Smoke Test 到 CI

**问题**: `smoke_test.sh` 存在但未在 CI 中运行

**方案**: 在 PR 环境部署后运行 smoke tests

```yaml
# .github/workflows/pr-test.yml
jobs:
  deploy-pr-env:
    # ... existing deploy steps ...
    
  smoke-test:
    needs: deploy-pr-env
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      
      - name: Run Smoke Tests
        run: |
          bash scripts/smoke_test.sh \
            "https://report-pr-${{ needs.deploy-pr-env.outputs.pr_number }}.zitian.party" \
            "staging"
      
      - name: Health Check Summary
        if: always()
        run: |
          echo "::notice::Smoke tests completed for PR #${{ needs.deploy-pr-env.outputs.pr_number }}"
```

---

#### 6. 测试数据管理策略

**问题**: 每个测试都手动创建数据，重复代码多

**方案**: Fixture Factory Pattern

```python
# apps/backend/tests/factories.py
from decimal import Decimal
from datetime import date
import factory

class AccountFactory(factory.Factory):
    class Meta:
        model = Account
    
    name = factory.Sequence(lambda n: f"Account {n}")
    type = AccountType.ASSET
    currency = "SGD"
    is_active = True

class JournalEntryFactory(factory.Factory):
    class Meta:
        model = JournalEntry
    
    entry_date = factory.LazyFunction(lambda: date.today())
    memo = "Test Transaction"
    status = JournalEntryStatus.POSTED
    
    @factory.post_generation
    def lines(self, create, extracted, **kwargs):
        if not create:
            return
        # Auto-generate balanced lines
        debit_account = AccountFactory(type=AccountType.ASSET)
        credit_account = AccountFactory(type=AccountType.INCOME)
        JournalLineFactory(entry=self, account=debit_account, direction=Direction.DEBIT, amount=100)
        JournalLineFactory(entry=self, account=credit_account, direction=Direction.CREDIT, amount=100)

# Usage in tests:
async def test_something(db):
    entry = JournalEntryFactory.create_async(user_id=user.id)
    await db.commit()
    # ...
```

---

### 长期 (3-6 月)

#### 7. Visual Regression Testing

**问题**: UI 变更难以发现

**方案**: Percy.io / Playwright Screenshots

```python
# tests/e2e/test_visual_regression.py
@pytest.mark.visual
async def test_dashboard_visual():
    """Screenshot comparison for dashboard."""
    page = await browser.new_page()
    await page.goto("http://localhost:3000/dashboard")
    await page.wait_for_selector('[data-testid="dashboard-loaded"]')
    await page.screenshot(path="screenshots/dashboard.png")
    # Percy compares with baseline
```

---

#### 8. Performance Testing

**问题**: 无性能基准

**方案**: Locust / k6 负载测试

```python
# tests/performance/locustfile.py
from locust import HttpUser, task, between

class FinanceReportUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def view_dashboard(self):
        self.client.get("/dashboard")
    
    @task(3)  # 权重更高
    def upload_statement(self):
        with open("fixtures/sample.pdf", "rb") as f:
            self.client.post("/api/statements/upload", files={"file": f})
```

---

## CI/CD 测试策略

### 测试分层执行

| 阶段 | 测试类型 | 触发时机 | 预期时长 |
|------|----------|----------|----------|
| **Pre-commit** | Lint, Format | Git hook | < 5s |
| **PR Open** | Unit Tests (96%) | Every push | 5-6 min |
| **PR Ready** | Integration Tests | After unit pass | 2-3 min |
| **PR Deploy** | Smoke Tests | After PR env deploy | 1 min |
| **Pre-merge** | E2E Tests (Critical) | Before merge | 5-10 min |
| **Post-merge** | Full E2E Suite | After merge to main | 15-20 min |
| **Nightly** | Performance Tests | Scheduled | 30 min |

---

## 测试命令规范

```bash
# 本地开发
moon run :test              # 单元测试 (快速)
moon run :test-integration  # 集成测试 (新增)
moon run :test-e2e          # E2E 测试 (新增)

# CI 专用
moon run :test                 # 全部测试
moon run :test -- --fast            # 关键路径测试 (快速验证)
moon run :smoke                    # Smoke 测试 (已存在)

# 覆盖率
moon run :test          # 生成覆盖率报告
```

---

## 测试可观测性

### 1. 测试报告面板

**工具**: Pytest HTML Report + Allure

```bash
# 生成 HTML 报告
pytest --html=report.html --self-contained-html

# 上传到 GitHub Actions Artifacts
- uses: actions/upload-artifact@v4
  with:
    name: test-report
    path: report.html
```

### 2. 测试失败通知

**方案**: GitHub Actions → Slack / Email

```yaml
- name: Notify on Test Failure
  if: failure()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    text: "Tests failed on PR #${{ github.event.pull_request.number }}"
```

### 3. 趋势分析

**工具**: Codecov / Coveralls (已集成)

**扩展**: 测试执行时间趋势、失败率趋势

---

## 优先级矩阵

| 改进项 | 影响力 | 实施成本 | 优先级 |
|--------|--------|----------|--------|
| 修复配置测试脆弱性 | 🔥 High | 💰 Low | **P0** (立即) |
| AI 模型调用集成测试 | 🔥 High | 💰 Medium | **P0** (本周) |
| Smoke Tests 集成到 CI | 🔥 High | 💰 Low | **P0** (本周) |
| 前端模型验证 E2E | 🔥 High | 💰 High | **P1** (2周内) |
| 完整 E2E 测试套件 | 🔥 High | 💰💰 High | **P1** (1月内) |
| 测试数据工厂 | 🔵 Medium | 💰 Medium | **P2** (2月内) |
| Visual Regression | 🔵 Medium | 💰💰 High | **P3** (3月内) |
| Performance Testing | 🔵 Low | 💰💰 High | **P3** (按需) |

---

## 成功指标

**短期目标 (1个月)**:
- [ ] 配置测试不再硬编码期望值
- [ ] AI 模型集成测试覆盖率 > 80%
- [ ] Smoke Tests 在 CI 中运行
- [ ] 至少 3 个关键 E2E 场景覆盖

**中期目标 (3个月)**:
- [ ] E2E 测试覆盖 5 个核心用户旅程
- [ ] 测试总执行时间 < 15 分钟
- [ ] 测试失败时有明确的错误信息
- [ ] PR 环境自动运行 smoke tests

**长期目标 (6个月)**:
- [ ] 测试金字塔平衡（70% Unit, 20% Integration, 10% E2E）
- [ ] 性能基准建立（P95 < 500ms）
- [ ] Visual Regression 覆盖关键页面
- [ ] 测试可观测性面板上线

---

## 总结

### 为什么测试没发现？

1. **测试存在** ✅ 但是 **断言硬编码** ❌
2. **单元测试充足** ✅ 但是 **集成测试不足** ⚠️
3. **Smoke Tests 存在** ✅ 但是 **未在 CI 运行** ❌
4. **缺少端到端验证** ❌ 无法发现实际运行时问题

### 最关键的 3 个改进

1. **配置契约测试** - 防止类似问题再次发生
2. **AI 模型集成测试** - 验证实际 API 调用
3. **Smoke Tests in CI** - 每次部署后验证基本功能

### 下一步行动

- [ ] 创建 Issue #151: "Add config contract tests"
- [ ] 创建 Issue #152: "Add AI model integration tests"
- [ ] 创建 Issue #153: "Integrate smoke tests into PR CI"
- [ ] 创建 Epic: "E2E Testing Infrastructure (Phase 1)"
