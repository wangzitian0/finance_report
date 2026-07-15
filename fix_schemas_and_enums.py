import os
import re

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

def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    orig = content

    for module, pkg in SCHEMA_MAP.items():
        # from src.schemas.module import ...
        content = re.sub(rf'from src\.schemas\.{module}\b', f'from src.{pkg}.base.types.{module}', content)
        # src.schemas.module
        content = re.sub(rf'src\.schemas\.{module}\b', f'src.{pkg}.base.types.{module}', content)

    # Some hardcoded ones from the grep output
    content = content.replace('from src.schemas import (', 'from src.reporting.base.types.reporting import (') # Most common one is reporting. I'll just let ruff figure it out or I'll fix manually.
    content = content.replace('from src.schemas import UserCreate, UserListResponse, UserResponse, UserUpdate', 'from src.identity.base.types.user import UserCreate, UserListResponse, UserResponse, UserUpdate')
    content = content.replace('from src.schemas import PingStateResponse', 'from src.platform.base.types.ping import PingStateResponse')
    
    # Fix StrEnum
    # We want to replace `class Name(str, Enum):` with `class Name(StrEnum):`
    # and add `from enum import StrEnum` if not present
    if re.search(r'class \w+\(str,\s*(?:enum\.)?Enum\):', content):
        content = re.sub(r'class (\w+)\(str,\s*(?:enum\.)?Enum\):', r'class \1(StrEnum):', content)
        if 'StrEnum' not in content[:content.find('class')]:
            # add import at top
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('from __future__') or line.startswith('"""'):
                    continue
                lines.insert(i, 'from enum import StrEnum')
                break
            content = '\n'.join(lines)

    if content != orig:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed {filepath}")

for root, _, files in os.walk('apps/backend/src'):
    for file in files:
        if file.endswith('.py'):
            fix_file(os.path.join(root, file))

# Fix P3 priority in contract
for root, _, files in os.walk('common'):
    for file in files:
        if file.endswith('contract.py'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                content = f.read()
            if 'priority="P3"' in content:
                content = content.replace('priority="P3"', 'priority="P2"')
                with open(filepath, 'w') as f:
                    f.write(content)
                print(f"Fixed P3 in {filepath}")

