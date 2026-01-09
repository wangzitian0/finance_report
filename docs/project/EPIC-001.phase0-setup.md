# EPIC-001: 基础设施与认证系统

> **Status**: 🟢 Complete  
> **Phase**: 0  
> **周期**: 2 周  
> **依赖**: 无  

---

## 🎯 目标

搭建可运行的 Monorepo 开发环境，完成用户认证与基础项目骨架。

**From [init.md Section 7](../../init.md) - Phase 0**

---

## 👥 角色审议

| 角色 | 关注点 | 审议意见 |
|------|--------|----------|
| 🏗️ **Architect** | 技术选型 | Moonrepo + FastAPI + Next.js 组合验证完毕，符合多语言 monorepo 需求 |
| 💻 **Developer** | 开发体验 | 热重载、类型提示、调试工具链完备 |
| 📋 **PM** | MVP 价值 | 最小可演示版本（ping-pong demo）验证端到端连通 |
| 🧪 **Tester** | 测试基础 | pytest + vitest 框架配置完成，CI 就绪 |

---

## ✅ 任务清单

### Moonrepo 工作区
- [x] 创建 `moon.yml` 工作区配置
- [x] 配置 `apps/backend/moon.yml` 任务
- [x] 配置 `apps/frontend/moon.yml` 任务
- [ ] 配置 `infra/moon.yml` 任务 (延后)

### Backend 骨架
- [x] FastAPI 项目结构 (`apps/backend/src/`)
- [x] FastAPI Users 认证集成 (注册/登录/JWT)
- [x] SQLAlchemy 2 + Alembic 配置
- [x] 健康检查接口 `/api/health`
- [x] structlog 结构化日志
- [ ] pre-commit hooks (black, ruff) → 技术债务

### Frontend 骨架
- [x] Next.js 14 App Router 初始化
- [x] shadcn/ui 组件库配置
- [x] TailwindCSS 设置
- [x] 最小化首页 (ping-pong demo)
- [x] TanStack Query 配置
- [ ] Zustand 状态管理 → EPIC-002

### Docker 环境
- [x] `docker-compose.yml` 本地开发
- [x] PostgreSQL 15 容器
- [x] Redis 7 容器 (可选)
- [x] 数据卷配置

---

## 📏 做得好不好的标准

### 🟢 合格标准 (Must Have)

| 标准 | 验证方法 | 状态 |
|------|----------|------|
| `docker compose up -d` 成功启动数据库 | 手动验证 | ✅ |
| `moon run backend:dev` 启动 FastAPI | 控制台无报错 | ✅ |
| `moon run frontend:dev` 启动 Next.js | 访问 localhost:3000 | ✅ |
| `/api/health` 返回 200 OK | curl 测试 | ✅ |
| 前后端 ping-pong 通信 | 页面显示 "pong" | ✅ |
| 用户注册/登录 API 可用 | Postman 测试 | ✅ |

### 🌟 优秀标准 (Nice to Have)

| 标准 | 验证方法 | 状态 |
|------|----------|------|
| GitHub Actions CI 配置 | PR 自动检查 | ⏳ |
| pre-commit hooks 配置 | 提交时自动格式化 | ⏳ |
| README 文档完整 | 新开发者 10 分钟上手 | ✅ |
| 测试覆盖率 > 50% | coverage report | ⏳ |

### 🚫 不合格信号

- 启动命令报错无法运行
- 数据库连接失败
- 认证接口返回 500 错误
- 前端无法访问后端 API

---

## 📚 SSOT 引用

- [schema.md](../ssot/schema.md) - 数据库结构
- [accounting.md](../ssot/accounting.md) - 会计模型

---

## 🔗 交付物

- [x] 可运行的 `apps/backend/` 项目
- [x] 可运行的 `apps/frontend/` 项目
- [x] `docker-compose.yml` 本地环境
- [x] `README.md` 快速开始指南

---

## 📝 技术债务

| 项目 | 优先级 | 计划解决时间 |
|------|--------|--------------|
| pre-commit hooks | P2 | EPIC-002 期间 |
| GitHub Actions CI | P1 | EPIC-002 完成前 |
| infra/moon.yml | P3 | 部署阶段 |

---

## ❓ Q&A (待确认问题)

> 本 EPIC 已完成，无待确认问题。

---

## 📅 时间线

- **开始**: 2026-01-06
- **完成**: 2026-01-09
- **实际工时**: ~12 小时
