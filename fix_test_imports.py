import re
from pathlib import Path
import os
import ast

# We need to replace `src.routers.<module>` with the new path!
# Let's see what the mapping is.
mapping = {
    "accounts": "ledger.extension.api.accounts",
    "app_config": "ui_core.extension.api.app_config",
    "assets": "portfolio.extension.api.assets",
    "audit": "audit.extension.api.audit",
    "chat": "advisor.extension.api.chat",
    "corrections": "extraction.extension.api.corrections", # wait, let's check
    "evidence": "extraction.extension.api.evidence",
    "income": "reporting.extension.api.income",
    "journal": "ledger.extension.api.journal",
    "llm": "llm.extension.api.llm",
    "metrics": "observability.extension.api.metrics",
    "portfolio": "portfolio.extension.api.portfolio",
    "reports": "reporting.extension.api.reports",
    "review": "extraction.extension.api.review",
    "statements": "extraction.extension.api.statements",
    "user_settings": "identity.extension.api.user_settings",
    "users": "identity.extension.api.users",
    "workflow": "platform.extension.api.workflow",
}

def fix_imports(content, filename):
    changed = False
    
    # 1. from src.routers.xyz import ...
    for k, v in mapping.items():
        old_imp = f"from src.routers.{k} "
        new_imp = f"from src.{v} "
        if old_imp in content:
            content = content.replace(old_imp, new_imp)
            changed = True
            
        old_imp = f"import src.routers.{k}"
        new_imp = f"import src.{v}"
        if old_imp in content:
            content = content.replace(old_imp, new_imp)
            changed = True
            
        # patch("src.routers.chat.AIAdvisorService")
        old_patch = f"\"src.routers.{k}."
        new_patch = f"\"src.{v}."
        if old_patch in content:
            content = content.replace(old_patch, new_patch)
            changed = True
            
        old_patch = f"'src.routers.{k}."
        new_patch = f"'src.{v}."
        if old_patch in content:
            content = content.replace(old_patch, new_patch)
            changed = True

    # test_api_surface_consistency.py might have `import src.routers as _routers_pkg`
    if "import src.routers as _routers_pkg" in content:
        # this file tests all routers, maybe we skip it or change it?
        pass

    return content, changed

for f in Path("apps/backend/tests").rglob("*.py"):
    with open(f, "r") as file:
        content = file.read()
        
    new_content, changed = fix_imports(content, str(f))
    
    if changed:
        with open(f, "w") as file:
            file.write(new_content)
        print(f"Fixed {f}")
        
