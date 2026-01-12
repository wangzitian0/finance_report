# 部署架构完整指南

## 概述

Finance Report 采用**三层环境架构**，从本地开发到生产，清晰分工、各司其职。

## 环境层级

### Layer 1️⃣：本地开发 & 本地 CI

**目的**：快速反馈，最小化环境依赖

| 方面 | 说明 |
|------|------|
| **工具** | moon、pytest、eslint（纯 CLI，无 Docker） |
| **命令** | `moon run backend:lint`、`pytest` |
| **特点** | 秒级反馈，使用 mock/local provider |
| **范围** | 代码验证、单元测试、类型检查 |

**不涉及 Docker，最快的开发循环**

---

### Layer 2️⃣：GitHub CI 和 PR 测试

**触发**：`git push` → PR 创建或更新 main 分支

| 方面 | 说明 |
|------|------|
| **Compose** | `docker-compose.yml`（本仓库） |
| **平台** | GitHub Actions（CI）+ Dokploy（PR test） |
| **构建** | 从源码 build（无镜像仓库）|
| **服务** | PostgreSQL、Redis、MinIO、Backend、Frontend |
| **数据** | 临时（GitHub Actions 自动清理） |
| **用途** | 集成测试、验证 PR 功能 |
| **URL** | GitHub CI 自动（无外部 URL） |

#### GitHub CI（`.github/workflows/ci.yml`）
- 运行 linter、backend tests、frontend build
- 启动 `docker-compose.yml` 用于集成测试
- 输出 coverage report

#### PR Test（`.github/workflows/pr-test.yml`）
- PR 创建时自动启动完整环境
- 域名：`report-pr-{number}.zitian.party`
- PR close 时自动销毁

**快速验证，无 Docker 镜像开销**

---

### Layer 3️⃣：Staging 和 Production（共享基础设施）

**共同特点**：
- Compose：`infra2` 仓库的参数化模板
- 镜像体系：GHCR 镜像仓库
- Secrets 管理：Vault（生产级安全）
- 平台：Dokploy（容器编排）

#### Staging 环境

**触发**：`main` 分支 push 时自动部署

| 方面 | 说明 |
|------|------|
| **Compose** | `infra2/finance_report/finance_report/10.app/compose.yaml` |
| **平台** | Dokploy（Projects > finance_report > staging） |
| **域名** | `report-staging.zitian.party` |
| **镜像 tag** | `sha-{commit_hash}` |
| **数据** | **持久化**（volumes 保留） |
| **Vault** | `secret/data/finance_report/staging/app` |
| **环境变量** | `ENV=staging` |
| **生命周期** | 长期（weeks/months） |
| **用途** | E2E 测试、Smoke 测试、持续验证 |

**Workflow：`.github/workflows/staging-deploy.yml`**
```
main push
  ↓
构建 backend/frontend 镜像
  ↓
Push 到 GHCR (tag: sha-xxx)
  ↓
调用 Dokploy API
  ↓
更新 IMAGE_TAG 环境变量
  ↓
重启应用（DB 数据保留）
```

#### Production 环境

**触发**：Release tag（语义化版本 `v1.2.3`）

| 方面 | 说明 |
|------|------|
| **Compose** | `infra2/finance_report/finance_report/10.app/compose.yaml` |
| **平台** | Dokploy（Projects > finance_report > production） |
| **域名** | `report.zitian.party` |
| **镜像 tag** | 语义化版本（`v1.2.3`） |
| **数据** | 关键业务数据 |
| **Vault** | `secret/data/finance_report/production/app` |
| **环境变量** | `ENV=production` |
| **生命周期** | 稳定 |
| **部署策略** | Blue-green 或 rolling update |

**Workflow：`.github/workflows/production-deploy.yml`**
```
release tag (v1.2.3)
  ↓
构建 backend/frontend 镜像
  ↓
Push 到 GHCR (tag: v1.2.3)
  ↓
调用 Dokploy API
  ↓
部署到 production
  ↓
自动 smoke test
```

---

## 文件清单

### Compose 文件

| 文件 | 用途 | 环境 |
|------|------|------|
| **`docker-compose.yml`** | 统一的 dev/CI/PR compose | local / GitHub CI / PR test |
| **`docker-compose.integration.yml`** | （待确认用途） | ? |
| **`infra2/.../compose.yaml`** | Staging & Production 模板 | staging / production |

### Workflow 文件

| 文件 | 触发 | 用途 |
|------|------|------|
| **`ci.yml`** | PR open/update + main push | 代码验证 + 集成测试 |
| **`pr-test.yml`** | PR open/sync/close | PR 测试环境（自动创建/销毁） |
| **`staging-deploy.yml`** | main push | 构建镜像 + 部署 staging |
| **`production-deploy.yml`** | release tag | 构建镜像 + 部署 production |

### 配置文件

#### Vault 结构
```
secret/data/finance_report/
├── staging/app
│   ├── DATABASE_URL
│   ├── REDIS_URL
│   ├── S3_ENDPOINT
│   ├── S3_ACCESS_KEY
│   ├── S3_SECRET_KEY
│   ├── S3_BUCKET
│   └── OPENROUTER_API_KEY
└── production/app
    └── （同上结构）
```

#### GitHub Secrets
| Secret | 用途 |
|--------|------|
| `DOKPLOY_API_KEY` | Dokploy API 认证 |
| `DOKPLOY_GITHUB_ID` | GitHub 集成 ID（`126refcRlCoWj6pmPXElU`） |
| `DOKPLOY_STAGING_ENV_ID` | Staging environment ID（`pMoEBQzZLZPWb1XwlvaNh`） |
| `DOKPLOY_PRODUCTION_ENV_ID` | Production environment ID |
| `VAULT_STAGING_TOKEN` | Vault staging token |
| `VAULT_PRODUCTION_TOKEN` | Vault production token |

---

## 开发工作流示例

### 开发新功能

```bash
# 1. 创建 feature branch
git checkout -b feat/add-dashboard

# 2. 本地开发 + 本地 CI 验证（快速反馈）
moon run backend:lint
pytest
moon run frontend:build

# 3. 如需完整环境，启动 Docker Compose
docker compose up -d

# 4. 提交并推送
git push origin feat/add-dashboard

# 5. 创建 PR
# → GitHub CI 自动验证
# → Dokploy 自动创建 PR test 环境
# → 获得 report-pr-{number}.zitian.party 域名进行功能测试

# 6. Review 和修改，每次 push 自动更新 PR test 环境

# 7. Merge PR
# → PR test 环境自动销毁
```

### 发布到 Staging

```bash
# 1. 代码合并到 main
git merge feat/add-dashboard

# 2. GitHub CI 验证
# → 所有 test 通过

# 3. 代码自动推送 staging
# → `staging-deploy.yml` 触发
# → 构建镜像（tag: sha-xxx）
# → 部署到 report-staging.zitian.party

# 4. QA / Smoke 测试
# → 使用持久化数据进行测试
```

### 发布到 Production

```bash
# 1. 创建 release tag
git tag v1.2.3
git push origin v1.2.3

# 2. GitHub Actions 触发
# → `production-deploy.yml` 运行
# → 构建镜像（tag: v1.2.3）
# → 部署到 report.zitian.party

# 3. 自动 smoke test

# 4. 监控生产环境
```

---

## 架构优势

| 优势 | 说明 |
|------|------|
| **快速反馈** | 本地 CLI 工具秒级验证 |
| **成本低** | GitHub CI 不构建镜像（早期阶段） |
| **隔离测试** | PR 自动创建完整隔离环境 |
| **数据持久** | Staging 保留测试数据供持续验证 |
| **版本管理** | Production 使用语义化版本，清晰稳定 |
| **灾难恢复** | Staging 和 Production 配置一致，便于对标 |

---

## 技术细节

### docker-compose.yml 的作用

1. **本地开发**：`docker compose up -d` 启动完整环境
2. **GitHub CI**：自动启动用于集成测试
3. **PR Test**：Dokploy 通过 GitHub 仓库读取并部署

### infra2 compose.yaml 的作用

1. **Staging/Production** 共享参数化模板
2. 通过环境变量区分 `ENV=staging` vs `ENV=production`
3. Vault agent 自动注入对应的 secrets
4. Traefik 标签用于路由和 SSL 证书

### 镜像 tag 策略

| 环境 | Tag | 说明 |
|------|-----|------|
| PR test | N/A | Docker compose build（无镜像） |
| Staging | `sha-{commit_hash}` | 追踪 main 最新版本 |
| Production | `v1.2.3` | 语义化版本，稳定 |

---

## 待完成事项

### Configuration（配置）
- [ ] 更新 README - 说明如何启动 docker-compose.yml
- [ ] GitHub repo settings 中配置 environment protection rules（可选）

### Testing（测试）
- [x] 本地 `docker compose up -d` 验证
- [x] GitHub CI 验证
- [x] 创建 test PR 验证完整流程
- [x] Staging 部署验证
- [x] Production 部署验证
