#!/bin/bash
# verify_logging_staging.sh - 验证 staging 环境的 logging 配置
# 
# 使用方法:
#   chmod +x verify_logging_staging.sh
#   ./verify_logging_staging.sh

set -e

echo "🔍 Verifying Docker logging configuration in staging environment..."
echo ""

# 获取 VPS_HOST
if [ -z "$VPS_HOST" ]; then
    echo "⚠️  VPS_HOST not set, retrieving from 1Password..."
    VPS_HOST=$(op item get nkl3hhoebk7tswzadm4iokpwni --vault=Infra2 --fields label=host --reveal 2>/dev/null)
    if [ -z "$VPS_HOST" ]; then
        echo "❌ Failed to retrieve VPS_HOST from 1Password"
        echo "   Please set VPS_HOST environment variable manually"
        exit 1
    fi
    echo "✅ VPS_HOST: $VPS_HOST"
fi
echo ""

# 获取所有 staging 容器
echo "📦 Fetching staging containers..."
CONTAINERS=$(ssh root@$VPS_HOST 'docker ps --filter name=-staging --format "{{.Names}}"' 2>/dev/null)

if [ -z "$CONTAINERS" ]; then
    echo "⚠️  No staging containers found"
    echo "   This is normal if staging environment hasn't been deployed yet"
    exit 0
fi

echo "Found staging containers:"
echo "$CONTAINERS" | sed 's/^/  - /'
echo ""

# 统计
TOTAL=0
CONFIGURED=0
MISSING=0

# 检查每个容器的 logging 配置
while IFS= read -r container; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📦 Container: $container"
    
    TOTAL=$((TOTAL + 1))
    
    # 获取 LogConfig
    LOG_CONFIG=$(ssh root@$VPS_HOST "docker inspect $container --format='{{json .HostConfig.LogConfig}}'" 2>/dev/null)
    
    # 检查是否包含我们的配置
    if echo "$LOG_CONFIG" | grep -q '"max-size":"5m"' && echo "$LOG_CONFIG" | grep -q '"max-file":"2"'; then
        echo "   ✅ Logging config: max-size=5m, max-file=2"
        CONFIGURED=$((CONFIGURED + 1))
    else
        echo "   ❌ Logging config missing or incorrect"
        echo "   Config: $LOG_CONFIG"
        MISSING=$((MISSING + 1))
    fi
    
    # 获取容器状态
    STATUS=$(ssh root@$VPS_HOST "docker inspect $container --format='{{.State.Status}}'" 2>/dev/null)
    if [ "$STATUS" = "running" ]; then
        echo "   🟢 Status: running"
    else
        echo "   🔴 Status: $STATUS"
    fi
    
    # 获取日志文件大小
    LOG_PATH=$(ssh root@$VPS_HOST "docker inspect $container --format='{{.LogPath}}'" 2>/dev/null)
    if [ -n "$LOG_PATH" ]; then
        LOG_SIZE=$(ssh root@$VPS_HOST "ls -lh '$LOG_PATH' 2>/dev/null | awk '{print \$5}'" 2>/dev/null || echo "N/A")
        echo "   📊 Current log size: $LOG_SIZE"
        
        # 检查是否有轮转的日志文件
        ROTATED_LOGS=$(ssh root@$VPS_HOST "ls -lh '$LOG_PATH'* 2>/dev/null | wc -l" 2>/dev/null || echo "1")
        if [ "$ROTATED_LOGS" -gt 1 ]; then
            echo "   🔄 Rotated log files: $ROTATED_LOGS"
        fi
    fi
    
    echo ""
done <<< "$CONTAINERS"

# 总结
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Summary:"
echo "   Total containers: $TOTAL"
echo "   ✅ Configured: $CONFIGURED"
echo "   ❌ Missing config: $MISSING"
echo ""

if [ $MISSING -eq 0 ]; then
    echo "🎉 All staging containers have correct logging configuration!"
    exit 0
else
    echo "⚠️  Some containers are missing logging configuration"
    echo "   Please redeploy these services to apply the new config"
    exit 1
fi
