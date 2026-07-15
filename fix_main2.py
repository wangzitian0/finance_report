
with open("apps/backend/src/main.py", "r") as f:
    content = f.read()

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

import_block = ""
for module, pkg in ROUTER_MAP.items():
    import_block += f"from src.{pkg}.extension.api import {module}\n"

content = content.replace('from fastapi import Depends, FastAPI, Request, Response', f'from fastapi import Depends, FastAPI, Request, Response\n{import_block}')

with open("apps/backend/src/main.py", "w") as f:
    f.write(content)

