import re

with open("apps/backend/src/main.py", "r") as f:
    content = f.read()

# In main.py we have:
# from src.routers import (
#     accounts,
#     ai_feedback,
#     app_config,
#     ...
# )
# And we have app.include_router(accounts.router) etc

# We should replace all usage of these routers with their new package imports.
# The map is:
ROUTER_MAP = {
    'accounts': 'ledger',
    'ai_feedback': 'identity',
    'app_config': 'ui_core',
    'assets': 'portfolio',
    'audit': 'audit',
    'chat': 'advisor',
    'classifications': 'extraction',
    'corrections': 'extraction',
    'evidence': 'extraction',
    'income': 'reporting',
    'journal': 'ledger',
    'llm': 'llm',
    'market_data': 'pricing',
    'metrics': 'observability',
    'portfolio': 'portfolio',
    'reconciliation': 'reconciliation',
    'reports': 'reporting',
    'review': 'extraction',
    'statements': 'extraction',
    'user_settings': 'identity',
    'workflow': 'platform'
}

# First, remove `from src.routers import (...)` entirely!
# It spans multiple lines.
content = re.sub(r'from src\.routers import \([\s\S]*?\)', '', content)
content = re.sub(r'from src\.routers import .*', '', content)

# Now, add the new imports at the top (after other imports)
import_block = ""
for module, pkg in ROUTER_MAP.items():
    import_block += f"from src.{pkg}.extension.api import {module}\n"

# insert it after `from fastapi import FastAPI`
if 'from fastapi import FastAPI' in content:
    content = content.replace('from fastapi import FastAPI', f'from fastapi import FastAPI\n{import_block}')

with open("apps/backend/src/main.py", "w") as f:
    f.write(content)
