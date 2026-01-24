# Staging 环境测试计划：Docker Logging 配置

## 📋 测试概述

**目标**: 验证 Docker logging 配置（max-size: 5m, max-file: 2）在 staging 环境正常工作

**影响范围**:
- Finance Report: 5 containers (postgres, redis, minio, backend, frontend)
- Platform Services: 27 containers across 9 services

**测试环境**: staging (容器名后缀 `-staging`)

---

## 🔧 前置准备

### 1. 确保 1Password CLI 已登录

```bash
# 检查登录状态
op account list

# 如果未登录，执行
op signin
```

### 2. 设置环境变量

```bash
# 在 repo 目录执行
cd repo

export DEPLOY_ENV=staging
export INTERNAL_DOMAIN=zitian.party
export VAULT_ADDR=https://vault.zitian.party
export VAULT_ROOT_TOKEN=$(op item get dexluuvzg5paff3cltmtnlnosm --vault=Infra2 --fields label=Token --reveal)
export VPS_HOST=$(op item get nkl3hhoebk7tswzadm4iokpwni --vault=Infra2 --fields label=host --reveal)
```

### 3. 验证连接

```bash
# 测试 SSH 连接
ssh root@$VPS_HOST "echo 'SSH connection OK'"

# 测试 Vault 连接
uv run invoke vault.status
```

---

## 🧪 测试步骤

### Phase 1: 测试单个服务（推荐先测试）

选择一个简单的服务测试配置是否正确：

```bash
cd repo

# 测试 Postgres (最简单的服务)
echo "🧪 Testing Postgres staging deployment..."
uv run invoke postgres.setup

# 检查部署状态
uv run invoke postgres.status

# 验证 logging 配置
ssh root@$VPS_HOST "docker inspect platform-postgres-staging | jq '.[0].HostConfig.LogConfig'"
```

**预期输出**:
```json
{
  "Type": "json-file",
  "Config": {
    "max-file": "2",
    "max-size": "5m"
  }
}
```

**如果成功** ✅: 继续 Phase 2

**如果失败** ❌: 
1. 检查 compose 文件语法
2. 查看容器日志: `ssh root@$VPS_HOST "docker logs platform-postgres-staging"`
3. 修复问题后重新部署

---

### Phase 2: 批量验证现有容器

使用验证脚本检查所有 staging 容器：

```bash
cd /Users/SP14016/zitian/finance_report2

# 赋予执行权限
chmod +x verify_logging_staging.sh

# 运行验证
./verify_logging_staging.sh
```

**脚本会检查**:
- ✅ Logging 配置是否正确 (max-size: 5m, max-file: 2)
- 🟢 容器运行状态
- 📊 当前日志文件大小
- 🔄 是否有轮转的日志文件

**示例输出**:
```
🔍 Verifying Docker logging configuration in staging environment...

📦 Fetching staging containers...
Found staging containers:
  - platform-postgres-staging
  - platform-redis-staging
  - platform-authentik-server-staging

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 Container: platform-postgres-staging
   ✅ Logging config: max-size=5m, max-file=2
   🟢 Status: running
   📊 Current log size: 245K
   
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Summary:
   Total containers: 3
   ✅ Configured: 3
   ❌ Missing config: 0

🎉 All staging containers have correct logging configuration!
```

---

### Phase 3: 部署其他平台服务（可选）

如果 Phase 1 和 2 都成功，可以部署其他服务：

```bash
cd repo

# 按依赖顺序部署
uv run invoke redis.setup
uv run invoke minio.setup
uv run invoke clickhouse.setup
uv run invoke authentik.setup
uv run invoke signoz.setup
uv run invoke portal.setup
uv run invoke activepieces.setup
uv run invoke prefect.setup

# 部署完成后，再次运行验证脚本
cd ..
./verify_logging_staging.sh
```

---

## 🔍 手动验证方法

### 检查单个容器的 logging 配置

```bash
# 查看 LogConfig
ssh root@$VPS_HOST "docker inspect platform-postgres-staging --format='{{json .HostConfig.LogConfig}}' | jq"

# 查看日志文件路径和大小
ssh root@$VPS_HOST "docker inspect platform-postgres-staging --format='{{.LogPath}}' | xargs ls -lh"

# 检查是否有轮转的日志文件
ssh root@$VPS_HOST "docker inspect platform-postgres-staging --format='{{.LogPath}}' | xargs -I {} ls -lh {}*"
```

### 批量检查所有 staging 容器

```bash
# 列出所有 staging 容器的 logging 配置
ssh root@$VPS_HOST 'docker ps --filter name=-staging --format "{{.Names}}" | while read name; do 
    echo "=== $name ===" 
    docker inspect $name --format="LogConfig: {{json .HostConfig.LogConfig}}" | jq
    docker inspect $name --format="LogPath: {{.LogPath}}" | xargs ls -lh 2>/dev/null || echo "No log file"
    echo ""
done'
```

---

## 📊 验证指标

### 成功标准

1. **容器启动**: 所有容器状态为 `running`
2. **Logging 配置**: LogConfig 包含 `"max-size":"5m"` 和 `"max-file":"2"`
3. **服务健康**: Health check 通过 (invoke xxx.status 返回 healthy)
4. **日志文件**: 
   - 当前日志 < 5MB
   - 最多 2 个日志文件（当前 + 轮转的）

### 失败处理

| 问题 | 解决方法 |
|------|---------|
| LogConfig 缺失 | 重新部署服务: `uv run invoke xxx.setup` |
| 容器启动失败 | 查看日志: `ssh root@$VPS_HOST "docker logs <container>"` |
| Health check 失败 | 检查依赖服务是否正常 (postgres, redis, vault) |
| 日志文件 > 5MB | 正常，等待轮转生效（新日志会被限制） |

---

## 🎯 测试场景

### Scenario 1: 新部署的服务
- 部署后立即检查 LogConfig
- 应该能看到正确的配置

### Scenario 2: 现有服务（未重新部署）
- 不会自动应用新配置
- 需要重新部署才能生效
- 验证脚本会标记为 "Missing config"

### Scenario 3: 日志轮转验证
- 如果日志接近 5MB，观察是否会自动创建 `.1` 后缀的文件
- 轮转后检查是否最多保留 2 个文件

---

## 📝 测试记录

请在测试后记录结果：

```bash
# 测试日期: _______________
# 操作人: _______________

## Phase 1: Postgres
- [ ] 部署成功
- [ ] LogConfig 正确
- [ ] 容器运行正常
- [ ] 日志文件 < 5MB

## Phase 2: 验证脚本
- [ ] 脚本执行成功
- [ ] 所有容器配置正确
- [ ] 无遗漏容器

## Phase 3: 其他服务 (可选)
- [ ] Redis
- [ ] MinIO
- [ ] ClickHouse
- [ ] Authentik
- [ ] SigNoz
- [ ] Portal
- [ ] Activepieces
- [ ] Prefect

## 问题记录
(如有问题请记录在此)

## 测试结论
- [ ] ✅ 通过，可以推广到 production
- [ ] ❌ 失败，需要修复: _____________
- [ ] ⏸️  部分通过，需要进一步测试
```

---

## 🚀 下一步

**如果测试通过**:
1. 提交代码到 Git
2. 创建 PR
3. 部署到 production

**推荐部署顺序**（production）:
```bash
# 1. Finance Report (主项目)
cd /Users/SP14016/zitian/finance_report2
docker compose up -d --force-recreate

# 2. Platform Services (repo)
cd repo
uv run invoke postgres.setup
uv run invoke redis.setup
uv run invoke minio.setup
uv run invoke clickhouse.setup
uv run invoke authentik.setup
uv run invoke signoz.setup
uv run invoke portal.setup
uv run invoke activepieces.setup
uv run invoke prefect.setup
```

---

## 📞 支持

如果遇到问题：
1. 查看容器日志
2. 检查 Vault 连接
3. 验证 SSH 权限
4. 查看 Dokploy 控制台

**调试命令**:
```bash
# 查看最近的容器日志
ssh root@$VPS_HOST "docker logs --tail 50 <container-name>"

# 检查容器状态
ssh root@$VPS_HOST "docker ps -a --filter name=<container-name>"

# 进入容器检查
ssh root@$VPS_HOST "docker exec -it <container-name> sh"
```
