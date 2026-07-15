import os
import re

ROUTER_EXPORTS = {
    'ledger': [('accounts', 'router', 'accounts_router'), ('journal', 'router', 'journal_router')],
    'identity': [('ai_feedback', 'router', 'ai_feedback_router'), ('user_settings', 'router', 'user_settings_router')],
    'ui_core': [('app_config', 'router', 'app_config_router')],
    'portfolio': [('assets', 'router', 'assets_router'), ('portfolio', 'router', 'portfolio_router')],
    'audit': [('audit', 'router', 'audit_router')],
    'advisor': [('chat', 'router', 'chat_router')],
    'extraction': [
        ('classifications', 'router', 'classifications_router'),
        ('corrections', 'router', 'corrections_router'),
        ('evidence', 'router', 'evidence_router'),
        ('statements', 'router', 'statements_router'),
        ('review', 'router', 'review_router'),
        ('review', 'conflicts_router', 'conflicts_router')
    ],
    'reporting': [('income', 'router', 'income_router'), ('reports', 'router', 'reports_router')],
    'llm': [('llm', 'router', 'llm_router')],
    'pricing': [('market_data', 'router', 'market_data_router')],
    'observability': [('metrics', 'router', 'metrics_router')],
    'platform': [('workflow', 'router', 'workflow_router')],
    'reconciliation': [('reconciliation', 'router', 'reconciliation_router')]
}

SCHEMA_EXPORTS = {
    'platform': [
        ('base.types.errors', ['COMMON_ERROR_RESPONSES', 'ErrorCode', 'ErrorResponse', 'error_code_for_status']),
        ('base.types.ping', ['PingStateResponse'])
    ]
}

# 1. Add exports to __init__.py of each package
for pkg, routers in ROUTER_EXPORTS.items():
    init_path = f'apps/backend/src/{pkg}/__init__.py'
    if not os.path.exists(init_path):
        open(init_path, 'w').close()
    
    with open(init_path, 'r') as f:
        content = f.read()

    new_exports = []
    for module, orig_name, new_name in routers:
        if new_name not in content:
            new_exports.append(f"from .extension.api.{module} import {orig_name} as {new_name}")
    
    if new_exports:
        with open(init_path, 'a') as f:
            f.write("\n" + "\n".join(new_exports) + "\n")

for pkg, schemas in SCHEMA_EXPORTS.items():
    init_path = f'apps/backend/src/{pkg}/__init__.py'
    if not os.path.exists(init_path):
        open(init_path, 'w').close()
    
    with open(init_path, 'r') as f:
        content = f.read()
    
    new_exports = []
    for mod, symbols in schemas:
        for sym in symbols:
            if sym not in content:
                new_exports.append(f"from .{mod} import {sym}")
    
    if new_exports:
        with open(init_path, 'a') as f:
            f.write("\n" + "\n".join(new_exports) + "\n")

# 2. Fix main.py imports
main_path = 'apps/backend/src/main.py'
with open(main_path, 'r') as f:
    main_content = f.read()

# Remove the previously injected direct extension/api imports
import_lines_to_remove = [
    "from src.ledger.extension.api import accounts, journal",
    "from src.identity.extension.api import ai_feedback, user_settings",
    "from src.ui_core.extension.api import app_config",
    "from src.portfolio.extension.api import assets, portfolio",
    "from src.audit.extension.api import audit",
    "from src.advisor.extension.api import chat",
    "from src.extraction.extension.api import classifications, corrections, evidence, statements, review",
    "from src.reporting.extension.api import income, reports",
    "from src.llm.extension.api import llm",
    "from src.pricing.extension.api import market_data",
    "from src.observability.extension.api import metrics",
    "from src.platform.extension.api import workflow",
    "from src.platform.base.types.errors import ErrorCode, ErrorResponse, error_code_for_status, COMMON_ERROR_RESPONSES",
    "from src.platform.base.types.ping import PingStateResponse",
    "from src.reconciliation.extension.api.reconciliation import router as reconciliation_router",
    "from src.reconciliation.extension.api import reconciliation"
]
for line in import_lines_to_remove:
    main_content = main_content.replace(line + "\n", "")
    main_content = main_content.replace(line, "")

# Add the correct imports from package roots
new_main_imports = """
from src.ledger import accounts_router, journal_router
from src.identity import ai_feedback_router, user_settings_router
from src.ui_core import app_config_router
from src.portfolio import assets_router, portfolio_router
from src.audit import audit_router
from src.advisor import chat_router
from src.extraction import classifications_router, corrections_router, evidence_router, statements_router, review_router, conflicts_router
from src.reporting import income_router, reports_router
from src.llm import llm_router
from src.pricing import market_data_router
from src.observability import metrics_router
from src.platform import workflow_router
from src.reconciliation import reconciliation_router
from src.platform import ErrorCode, ErrorResponse, error_code_for_status, COMMON_ERROR_RESPONSES, PingStateResponse
"""
# insert near top of imports
main_content = re.sub(
    r'(from src.schemas.errors import ErrorCode, ErrorResponse, error_code_for_status, COMMON_ERROR_RESPONSES)?', 
    '', 
    main_content
)

# find an anchor
anchor = "from src.routers.reconciliation import router as reconciliation_router"
main_content = main_content.replace(anchor, "")

# Add imports
parts = main_content.split("from src.config import settings")
main_content = parts[0] + new_main_imports.strip() + "\nfrom src.config import settings" + parts[1]

# Now, fix the router inclusions
replacements = {
    'accounts.router': 'accounts_router',
    'app_config.router': 'app_config_router',
    'ai_feedback.router': 'ai_feedback_router',
    'audit.router': 'audit_router',
    'assets.router': 'assets_router',
    'chat.router': 'chat_router',
    'classifications.router': 'classifications_router',
    'corrections.router': 'corrections_router',
    'evidence.router': 'evidence_router',
    'journal.router': 'journal_router',
    'market_data.router': 'market_data_router',
    'metrics.router': 'metrics_router',
    'income.router': 'income_router',
    'reports.router': 'reports_router',
    'statements.router': 'statements_router',
    'review.router': 'review_router',
    'review.conflicts_router': 'conflicts_router',
    'user_settings.router': 'user_settings_router',
    'llm.router': 'llm_router',
    'portfolio.router': 'portfolio_router',
    'workflow.router': 'workflow_router',
}
for old, new in replacements.items():
    main_content = main_content.replace(old, new)

with open(main_path, 'w') as f:
    f.write(main_content)
print("Boundary fixes applied.")
