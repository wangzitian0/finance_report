import re
import os

ROUTER_EXPORTS = {
    'ledger': ['accounts_router', 'journal_router'],
    'identity': ['ai_feedback_router', 'user_settings_router'],
    'ui_core': ['app_config_router'],
    'portfolio': ['assets_router', 'portfolio_router'],
    'audit': ['audit_router'],
    'advisor': ['chat_router'],
    'extraction': ['classifications_router', 'corrections_router', 'evidence_router', 'statements_router', 'review_router', 'conflicts_router'],
    'reporting': ['income_router', 'reports_router'],
    'llm': ['llm_router'],
    'pricing': ['market_data_router'],
    'observability': ['metrics_router'],
    'platform': ['workflow_router'],
    'reconciliation': ['reconciliation_router']
}

SCHEMA_EXPORTS = {
    'platform': [
        'COMMON_ERROR_RESPONSES', 'ErrorCode', 'ErrorResponse', 'error_code_for_status', 'PingStateResponse'
    ]
}

def inject_list(content, var_name, new_items):
    # This regex is a bit complex but looks for `var_name = [ ... ]`
    # and inserts before the closing `]`
    # We can also just find the start of the list and append.
    
    # Try to find exactly var_name = [ ... ]
    # In some files it's `__all__ = [\n` or `interface=[\n`
    # Since formatting can be tricky, let's just do a string manipulation:
    
    if var_name == "__all__":
        pattern = re.compile(r'__all__\s*=\s*\[(.*?)\]', re.DOTALL)
    elif var_name == "_EXTENSION_EXPORTS":
        pattern = re.compile(r'_EXTENSION_EXPORTS\s*=\s*\{(.*?)\}', re.DOTALL)
    else:
        pattern = re.compile(r'interface\s*=\s*\[(.*?)\]', re.DOTALL)

    match = pattern.search(content)
    if not match:
        return content
    
    inner = match.group(1)
    
    # Check if items are already there
    to_add = []
    for item in new_items:
        if f'"{item}"' not in inner and f"'{item}'" not in inner:
            to_add.append(f'"{item}"')
            
    if not to_add:
        return content
        
    add_str = ",\n    " + ",\n    ".join(to_add)
    
    # If inner ends with trailing comma, we don't need a comma
    if inner.strip().endswith(','):
        add_str = "\n    " + ",\n    ".join(to_add) + ","
    else:
        # if inner is not empty and doesn't end with comma
        if inner.strip():
            add_str = "," + add_str + ","
        else:
            add_str = "\n    " + ",\n    ".join(to_add) + ","
            
    new_inner = inner + add_str
    
    if var_name == "__all__":
        new_content = content[:match.start(1)] + new_inner + content[match.end(1):]
    elif var_name == "_EXTENSION_EXPORTS":
        new_content = content[:match.start(1)] + new_inner + content[match.end(1):]
    else:
        new_content = content[:match.start(1)] + new_inner + content[match.end(1):]
        
    return new_content

for pkg, items in ROUTER_EXPORTS.items():
    # Update __init__.py
    init_path = f'apps/backend/src/{pkg}/__init__.py'
    if os.path.exists(init_path):
        with open(init_path, 'r') as f:
            content = f.read()
        
        # special case for identity _EXTENSION_EXPORTS
        if pkg == 'identity':
            content = inject_list(content, '_EXTENSION_EXPORTS', items)
            
        content = inject_list(content, '__all__', items)
        with open(init_path, 'w') as f:
            f.write(content)

    # Update contract.py
    contract_path = f'common/{pkg}/contract.py'
    if os.path.exists(contract_path):
        with open(contract_path, 'r') as f:
            content = f.read()
        content = inject_list(content, 'interface', items)
        with open(contract_path, 'w') as f:
            f.write(content)

for pkg, items in SCHEMA_EXPORTS.items():
    init_path = f'apps/backend/src/{pkg}/__init__.py'
    if os.path.exists(init_path):
        with open(init_path, 'r') as f:
            content = f.read()
        content = inject_list(content, '__all__', items)
        with open(init_path, 'w') as f:
            f.write(content)
            
    contract_path = f'common/{pkg}/contract.py'
    if os.path.exists(contract_path):
        with open(contract_path, 'r') as f:
            content = f.read()
        content = inject_list(content, 'interface', items)
        with open(contract_path, 'w') as f:
            f.write(content)

print("Updated __all__ and contract.py")
