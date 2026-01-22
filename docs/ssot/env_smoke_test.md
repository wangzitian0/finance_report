# Environment Variable Smoke Testing

## Overview

The environment smoke test validates that your configuration not only exists but actually **works** by performing real operations on each service.

## Quick Start

```bash
# Full smoke test (all services)
moon run backend:env-check

# Quick mode (skip optional services like Redis, OpenRouter)
moon run backend:env-check-quick

# Or run directly
cd apps/backend
uv run python -m src.env_smoke_test
uv run python -m src.env_smoke_test --quick
```

## What It Tests

### ✅ Database (PostgreSQL)
- **Connection**: Verify `DATABASE_URL` works
- **Operations**: Create temp table, insert, select
- **Expected**: Should complete in < 1000ms

### ✅ MinIO/S3
- **Connection**: Verify `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` work
- **Operations**: Upload test file, download, generate presigned URL, delete
- **Expected**: Should complete in < 2000ms

### ⚠️ Redis (Optional)
- **Connection**: Verify `REDIS_URL` works (if configured)
- **Operations**: Ping, set key, get key, delete key
- **Expected**: Should complete in < 500ms
- **Note**: Skipped if `REDIS_URL` not set (local dev OK)

### ⚠️ OpenRouter (Optional)
- **Connection**: Verify `OPENROUTER_API_KEY` works (if configured)
- **Operations**: Fetch model list, verify primary model available
- **Expected**: Should complete in < 3000ms
- **Note**: Skipped if `OPENROUTER_API_KEY` not set (AI features disabled)

## Example Output

```
================================================================================
Environment Smoke Test Results
================================================================================

✅ DATABASE (245ms)
   Connection, create table, insert, select all OK

✅ MINIO (892ms)
   Upload, download, presigned URL, delete all OK
   - test_key: smoke_test/20260122_203045_123456.txt
   - content_size: 48

⏭️ REDIS
   REDIS_URL not configured (optional for local dev)

⚠️ OPENROUTER (1234ms)
   API key valid, 127 models available
   - primary_model: google/gemini-2.0-flash-exp:free
   - primary_available: True

================================================================================

Summary: 2 OK, 1 warnings, 0 errors, 1 skipped

⚠️  Some optional services unavailable - features may be degraded
================================================================================
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All tests passed (warnings OK) |
| `1` | At least one test failed (error status) |

Use `--fail-on-warning` to treat warnings as errors:

```bash
uv run python -m src.env_smoke_test --fail-on-warning
```

## When to Use

### Local Development Setup
```bash
# After setting up .env for the first time
moon run backend:env-check

# Verify everything works before starting dev server
moon run backend:dev
```

### CI/CD Pipeline
```bash
# In GitHub Actions / deployment scripts
moon run backend:env-check-quick
if [ $? -ne 0 ]; then
  echo "Environment validation failed"
  exit 1
fi
```

### Debugging Configuration Issues
```bash
# When uploads fail with "S3 not configured"
moon run backend:env-check

# Output will show exactly what's wrong:
# ❌ MINIO (150ms)
#    MinIO test failed: Failed to access bucket statements
```

### PR Environment Validation
```bash
# After PR environment deploys
curl https://report-pr-123.zitian.party/api/health

# Or SSH into server and run smoke test
ssh root@$VPS_HOST
docker exec finance-report-backend-pr-123 python -m src.env_smoke_test
```

## Troubleshooting

### Database Connection Failed
```
❌ DATABASE
   Database test failed: asyncpg.exceptions.InvalidPasswordError
```

**Fix**: Check `DATABASE_URL` in `.env` or Vault secrets.

### MinIO Upload Failed
```
❌ MINIO
   MinIO test failed: Failed to create bucket statements
```

**Fixes**:
1. Check `S3_ENDPOINT` is reachable (try `curl $S3_ENDPOINT`)
2. Verify `S3_ACCESS_KEY` and `S3_SECRET_KEY` are correct
3. Check bucket `S3_BUCKET` exists or service has create permission

### OpenRouter API Key Invalid
```
❌ OPENROUTER
   API key invalid (401 Unauthorized)
```

**Fix**: Get valid key from https://openrouter.ai/keys and update `OPENROUTER_API_KEY`.

## Implementation Details

**File**: `apps/backend/src/env_smoke_test.py`

The smoke test:
1. Reads configuration from `src.config.settings`
2. Performs actual operations (not just checking existence)
3. Cleans up test data after each test
4. Runs tests in parallel where possible (DB first, then others)
5. Returns structured results with timing information

**Test Isolation**: All test keys/data use timestamps to avoid conflicts:
- Database: Temporary tables (auto-dropped)
- MinIO: Keys like `smoke_test/20260122_203045.txt` (deleted after test)
- Redis: Keys like `smoke_test:2026-01-22T20:30:45Z` (10s TTL + explicit delete)

## Integration with Existing Tools

### Compared to `src.env_check.py`
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `env_check.py` | Checks if variables **exist** | Startup validation |
| `env_smoke_test.py` | Tests if variables **work** | Pre-deployment, debugging |

Both are complementary:
- `env_check.py` runs on server startup (fast, blocking)
- `env_smoke_test.py` runs on-demand (slower, comprehensive)

### Compared to Health Check Endpoint
| Tool | Scope | Usage |
|------|-------|-------|
| `/health` endpoint | Application status | Load balancer checks |
| `env_smoke_test.py` | Configuration validation | Deployment verification |

Health check is lightweight (database ping only). Smoke test is comprehensive (all services + operations).

## Future Enhancements

Potential additions:
- [ ] Test S3 public endpoint if configured
- [ ] Test AI extraction with sample image (full e2e)
- [ ] Test FX rate API connectivity
- [ ] Prometheus metrics export
- [ ] Slack/Discord notification on failure
- [ ] Integration with `scripts/smoke_test.sh` (e2e HTTP tests)

## See Also

- [development.md](./docs/ssot/development.md) - Development workflow
- [extraction.md](./docs/ssot/extraction.md) - Storage configuration details
- [.env.example](../../.env.example) - Environment variable reference
