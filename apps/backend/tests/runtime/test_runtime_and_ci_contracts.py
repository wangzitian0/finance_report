from __future__ import annotations

from fastapi.routing import iter_route_contexts
from src.config import settings
from src.ledger import AccountType
from src.main import app
from src.schemas.account import AccountCreate


def test_runtime_and_ci_contracts() -> None:
    route_paths = [getattr(context.route, "path", None) for context in iter_route_contexts(app.routes)]
    assert "/health" in route_paths

    db_url = str(settings.database_url).lower()
    assert "production" not in db_url and "prod.internal" not in db_url

    schema = AccountCreate(name="Operating Checking", type=AccountType.ASSET, currency="SGD")
    assert (schema.type, schema.currency) == (AccountType.ASSET, "SGD")
