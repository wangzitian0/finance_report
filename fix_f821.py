
files = [
    "apps/backend/src/advisor/orm/chat.py",
    "apps/backend/src/audit/promotion/gate.py",
    "apps/backend/src/audit/source_type_priority.py",
    "apps/backend/src/boot.py",
    "apps/backend/src/extraction/extension/_llm_led_gate.py",
    "apps/backend/src/extraction/extension/transaction_classification.py",
    "apps/backend/src/extraction/orm/statement_enums.py",
    "apps/backend/src/portfolio/orm/portfolio.py",
    "apps/backend/src/pricing/orm/market_data_override.py",
    "apps/backend/src/reconciliation/orm/reconciliation.py",
    "apps/backend/src/runtime/base/check.py",
    "apps/backend/src/runtime/base/kind.py",
    "apps/backend/src/runtime/base/tiers.py",
    "apps/backend/src/runtime/extension/snapshot_anonymizer.py"
]

for f in files:
    with open(f, 'r') as file:
        lines = file.readlines()
    
    # Remove bad injections
    cleaned = []
    for line in lines:
        if line.startswith('from enum import Enum, StrEnum'):
            pass
        elif line.startswith('from enum import StrEnum'):
            pass
        else:
            cleaned.append(line)
            
    # Now find the first `import ` or `from ` that is NOT `__future__`
    insert_idx = 0
    for i, line in enumerate(cleaned):
        if line.startswith('import ') or (line.startswith('from ') and '__future__' not in line):
            insert_idx = i
            break
            
    cleaned.insert(insert_idx, 'from enum import Enum, StrEnum\n')
    
    with open(f, 'w') as file:
        file.writelines(cleaned)

