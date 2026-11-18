from __future__ import annotations

from pathlib import Path

from fastapi.routing import iter_route_contexts
from src.config import settings
from src.ledger import AccountType
from src.main import app
from src.schemas.account import AccountCreate

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_runtime_and_ci_contracts() -> None:
    route_paths = [getattr(context.route, "path", None) for context in iter_route_contexts(app.routes)]
    assert "/health" in route_paths

    next_cfg = next((p for p in (REPO_ROOT / "apps" / "frontend" / "next.config.js", REPO_ROOT / "apps" / "frontend" / "next.config.mjs") if p.exists()), None)
    assert next_cfg is not None and any(tok in next_cfg.read_text(encoding="utf-8") for tok in ("rewrites", "env", "destination", "BACKEND_URL"))

    db_url = str(settings.database_url).lower()
    assert "production" not in db_url and "prod.internal" not in db_url

    ci_yml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "backend:" in ci_yml and "frontend-vitest:" in ci_yml and "ac-traceability:" not in ci_yml
    assert (REPO_ROOT / "tools" / "preflight.py").exists()

    schema = AccountCreate(name="Operating Checking", type=AccountType.ASSET, currency="SGD")
    assert (schema.type, schema.currency) == (AccountType.ASSET, "SGD")
