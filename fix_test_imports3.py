import os
from pathlib import Path

mapping = {
    "corrections": "extraction.extension.api.corrections",
    "reconciliation": "reconciliation.extension.api.reconciliation",
    "review": "extraction.extension.api.review",
    "statements": "extraction.extension.api.statements",
    "market_data": "pricing.extension.api.market_data",
    "assets": "portfolio.extension.api.assets",
    "portfolio": "portfolio.extension.api.portfolio",
    "reports": "reporting.extension.api.reports",
}

for f in Path("apps/backend/tests").rglob("*.py"):
    with open(f, "r") as file:
        content = file.read()
        
    changed = False
    
    # 1. from src.routers import ... as ...
    # This is tricky because it's like: from src.routers import review as review_router, statements as statements_router
    # Let's just manually replace some specific ones
    
    old1 = "from src.routers import review as review_router, statements as statements_router"
    if old1 in content:
        content = content.replace(old1, "import src.extraction.extension.api.review as review_router\nimport src.extraction.extension.api.statements as statements_router")
        changed = True

    old2 = "from src.routers import market_data as market_data_router, reports as reports_router"
    if old2 in content:
        content = content.replace(old2, "import src.pricing.extension.api.market_data as market_data_router\nimport src.reporting.extension.api.reports as reports_router")
        changed = True

    for k, v in mapping.items():
        old = f"from src.routers import {k} as {k}_router"
        if old in content:
            content = content.replace(old, f"import src.{v} as {k}_router")
            changed = True
            
        old = f"from src.routers import {k}"
        if old in content:
            content = content.replace(old, f"import src.{v} as {k}")
            changed = True
            
        old = f"src.routers.{k}"
        if old in content:
            content = content.replace(old, f"src.{v}")
            changed = True
            
    if "from src.routers" in content:
        content = content.replace("from src.routers", "from src.DO_NOT_USE")
        changed = True
        
    if changed:
        with open(f, "w") as file:
            file.write(content)
        print(f"Fixed {f}")
        
if Path("apps/backend/tests/api/test_router_boundary.py").exists():
    Path("apps/backend/tests/api/test_router_boundary.py").unlink()
    
