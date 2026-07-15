import os
import shutil
import re
from pathlib import Path

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

SCHEMA_MAP = {
    'account': 'ledger',
    'app_config': 'ui_core',
    'assets': 'portfolio',
    'audit': 'audit',
    'base': 'platform',
    'chat': 'advisor',
    'errors': 'platform',
    'evidence': 'extraction',
    'extraction': 'extraction',
    'income': 'reporting',
    'journal': 'ledger',
    'llm': 'llm',
    'metrics': 'observability',
    'ping': 'platform',
    'portfolio': 'portfolio',
    'provenance': 'platform',
    'reconciliation': 'reconciliation',
    'reporting': 'reporting',
    'review': 'extraction',
    'streaming': 'platform',
    'user': 'identity',
    'workflow': 'platform'
}

SRC_DIR = Path('apps/backend/src')
TEST_DIR = Path('tests')

def replace_in_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    orig_content = content
    
    # Replace router imports
    for module, pkg in ROUTER_MAP.items():
        content = re.sub(
            rf'from src\.routers\.{module}\s+import',
            f'from src.{pkg}.extension.api.{module} import',
            content
        )
        content = re.sub(
            rf'from src\.routers\s+import\s+{module}',
            f'from src.{pkg}.extension.api import {module}',
            content
        )
        # handle multi-line imports from src.routers
        content = re.sub(
            rf'src\.routers\.{module}',
            f'src.{pkg}.extension.api.{module}',
            content
        )
        
    # Replace schema imports
    for module, pkg in SCHEMA_MAP.items():
        content = re.sub(
            rf'from src\.schemas\.{module}\s+import',
            f'from src.{pkg}.base.types.{module} import',
            content
        )
        content = re.sub(
            rf'from src\.schemas\s+import\s+{module}',
            f'from src.{pkg}.base.types import {module}',
            content
        )
        content = re.sub(
            rf'src\.schemas\.{module}',
            f'src.{pkg}.base.types.{module}',
            content
        )

    # Some direct src.schemas imports without module (like from src.schemas import User)
    schemas_direct = {
        'identity': ['UserCreate', 'UserListResponse', 'UserResponse', 'UserUpdate'],
        'reporting': ['AnnualizedIncomeScheduleHolding', 'TrendPeriod', 'NetWorthGranularity', 'BreakdownPeriod', 'BreakdownType', 'PersonalReportingFrameworkId', 'ReportLineId', 'PolicyDimension', 'PolicyFactDomain', 'PolicyProvenance', 'PolicyReviewState', 'PersonalReportPackageReadinessState', 'PersonalReportPackageSnapshotStatus'],
        'extraction': ['DocumentStatus', 'DocumentType', 'Stage1Status', 'BankStatementStatus'],
        'ledger': ['AccountType', 'JournalEntryStatus', 'Direction'],
        'platform': ['PingStateResponse', 'COMMON_ERROR_RESPONSES', 'ErrorCode', 'ErrorResponse', 'error_code_for_status']
    }
    
    # Generic replacements for direct src.schemas imports
    for pkg, symbols in schemas_direct.items():
        for sym in symbols:
            # Need to be careful with multi-line imports from src.schemas
            pass
            
    if content != orig_content:
        with open(filepath, 'w') as f:
            f.write(content)

# 1. Move files
for module, pkg in ROUTER_MAP.items():
    src_file = SRC_DIR / 'routers' / f'{module}.py'
    dest_dir = SRC_DIR / pkg / 'extension' / 'api'
    dest_file = dest_dir / f'{module}.py'
    if src_file.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
        # ensure __init__.py exists
        (dest_dir.parent / '__init__.py').touch()
        (dest_dir / '__init__.py').touch()
        shutil.move(str(src_file), str(dest_file))

for module, pkg in SCHEMA_MAP.items():
    src_file = SRC_DIR / 'schemas' / f'{module}.py'
    dest_dir = SRC_DIR / pkg / 'base' / 'types'
    dest_file = dest_dir / f'{module}.py'
    if src_file.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir.parent / '__init__.py').touch()
        (dest_dir / '__init__.py').touch()
        shutil.move(str(src_file), str(dest_file))

# 2. Update imports globally
for filepath in SRC_DIR.rglob('*.py'):
    replace_in_file(filepath)
for filepath in TEST_DIR.rglob('*.py'):
    replace_in_file(filepath)

# 3. Handle remaining direct `from src.schemas import` multi-line/inline imports
files_to_fix = {
    'apps/backend/src/identity/extension/api/users.py': ('from src.schemas import', 'from src.identity.base.types.user import'),
    'apps/backend/src/advisor/extension/annualized_income.py': ('from src.schemas import (', 'from src.reporting.base.types.reporting import ('),
    'apps/backend/src/extraction/extension/api/statements.py': ('from src.schemas import (', 'from src.extraction.base.types.extraction import ('),
    'apps/backend/src/ledger/extension/api/accounts.py': ('from src.schemas import (', 'from src.ledger.base.types.account import ('),
    'apps/backend/src/ledger/extension/api/journal.py': ('from src.schemas import (', 'from src.ledger.base.types.journal import ('),
    'apps/backend/src/reporting/extension/api/reports.py': ('from src.schemas import (', 'from src.reporting.base.types.reporting import ('),
    'apps/backend/src/reporting/extension/report_package.py': ('from src.schemas import (', 'from src.reporting.base.types.reporting import (')
}

for filepath, (old, new) in files_to_fix.items():
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            content = f.read()
        content = content.replace(old, new)
        with open(filepath, 'w') as f:
            f.write(content)

print("Moved files and updated imports.")
