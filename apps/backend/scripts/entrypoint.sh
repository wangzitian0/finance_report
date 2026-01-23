#!/bin/bash
set -e

export PYTHONPATH=$PYTHONPATH:.
export PATH=$PATH:$(pwd)

echo "🚀 Starting container entrypoint..."

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
    
    sync_url = url.replace("postgresql+asyncpg://", "postgresql://")

    print("⏳ Waiting for database...")
    conn = None
    last_error = None
    for i in range(60):
        try:
            conn = psycopg2.connect(sync_url, connect_timeout=5)
            break
        except Exception as e:
            last_error = e
            if i == 0:
                print(f"  Database not ready: {type(e).__name__}")
                print(f"  Retrying connection...")
            if i % 10 == 9:
                print(f"  Still waiting ({i+1}/60)...")
                print(f"    Last error: {type(e).__name__}: {e}")
            time.sleep(1)
    
    if not conn:
        print("❌ ERROR: Database connection timeout (60s)")
        if last_error:
            print(f"   Last error: {type(last_error).__name__}: {last_error}")
        sys.exit(1)
    
    print("✅ Database connected")

    try:
        conn.set_session(autocommit=True)
        with conn.cursor() as cur:
            lock_id = 1862534
            print(f"🔒 Acquiring migration lock...")
            cur.execute("SELECT pg_advisory_lock(%s);", (lock_id,))

            try:
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

                if table_count > 0 and not has_alembic:
                    print(f"⚠️  Stamping {table_count} existing tables...")
                    command.stamp(alembic_cfg, "head")
                
                print("🚀 Running migrations...")
                start = time.time()
                command.upgrade(alembic_cfg, "head")
                duration = time.time() - start
                print(f"✅ Database ready (migrations took {duration:.1f}s)")
            finally:
                # Explicitly release advisory lock to ensure clean handoff.
                # While PostgreSQL auto-releases locks on connection close,
                # explicit release prevents edge cases where connection pooling
                # or abnormal termination could delay lock release.
                cur.execute("SELECT pg_advisory_unlock(%s);", (lock_id,))

    except Exception as e:
        print(f"❌ Migration failed: {type(e).__name__}")
        print(f"   {str(e)}")
        import traceback
        print("\nStacktrace:")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_db_setup()
EOF

echo "🎬 Starting application..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000