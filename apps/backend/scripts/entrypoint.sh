#!/bin/bash
set -e

# --- 顶级 Infra 专家：自愈与泛化探测 ---

# 1. 解决环境变量与路径问题
export PYTHONPATH=$PYTHONPATH:.
# 强制将当前目录加入 PATH，确保能找到 alembic
export PATH=$PATH:$(pwd)

echo "🚀 Starting robust entrypoint process..."

# 2. 执行 Python 引导脚本 (封装 锁 + 探测 + 迁移)
# 使用 'EOF' 防止 Shell 干扰
python3 - << 'EOF'
import os
import sys
import time
import psycopg2
from alembic.config import Config
from alembic import command

def run_db_setup():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("❌ ERROR: DATABASE_URL not set")
        sys.exit(1)
    
    # 适配驱动
    sync_url = url.replace("postgresql+asyncpg://", "postgresql://")

    # A. 拨测 SQL 连通性
    conn = None
    for i in range(60):
        try:
            conn = psycopg2.connect(sync_url, connect_timeout=5)
            break
        except Exception as e:
            print(f"  ... waiting for SQL ({i}/60): {e}")
            time.sleep(1)
    
    if not conn:
        print("❌ ERROR: DB connection failed")
        sys.exit(1)

    try:
        conn.set_session(autocommit=True)
        with conn.cursor() as cur:
            # B. 获取分布式锁 (项目专属 ID)
            lock_id = 1862534
            print(f"🔒 Acquiring advisory lock ({lock_id})...")
            cur.execute("SELECT pg_advisory_lock(%s);", (lock_id,))
            print("✅ Lock acquired.")

            # C. 泛化探测：检查 public 下是否有任何业务表
            # 排除 alembic 自己的版本表，检查是否已有存量数据结构
            cur.execute("""
                SELECT count(*) FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name != 'alembic_version'
            """)
            table_count = cur.fetchone()[0]

            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = 'alembic_version'
                )
            """)
            has_alembic = cur.fetchone()[0]

            alembic_cfg = Config("alembic.ini")
            alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

            # D. 智能决策：存量接管逻辑
            if table_count > 0 and not has_alembic:
                print(f"⚠️  Detected {table_count} existing tables without Alembic history. Stamping...")
                command.stamp(alembic_cfg, "head")
            
            # E. 执行升级
            print("🚀 Running migrations...")
            command.upgrade(alembic_cfg, "head")
            print("✅ Database is up-to-date.")

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        sys.exit(1)
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_db_setup()
EOF

# 3. 启动应用 (使用 exec 保持 PID 1)
echo "🎬 Application launching..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000