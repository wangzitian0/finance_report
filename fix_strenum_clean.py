
files = [
    'apps/backend/src/advisor/orm/chat.py',
    'apps/backend/src/audit/promotion/gate.py',
    'apps/backend/src/audit/source_type_priority.py',
    'apps/backend/src/boot.py',
    'apps/backend/src/extraction/extension/_llm_led_gate.py',
    'apps/backend/src/extraction/extension/transaction_classification.py',
    'apps/backend/src/extraction/orm/statement_enums.py',
    'apps/backend/src/platform/base/types/errors.py',
    'apps/backend/src/platform/base/types/streaming.py',
    'apps/backend/src/portfolio/orm/portfolio.py',
    'apps/backend/src/pricing/orm/market_data_override.py',
    'apps/backend/src/reconciliation/orm/reconciliation.py',
    'apps/backend/src/runtime/base/check.py',
    'apps/backend/src/runtime/base/kind.py',
    'apps/backend/src/runtime/base/tiers.py',
    'apps/backend/src/runtime/extension/snapshot_anonymizer.py'
]

for filepath in files:
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
            
        # Remove all existing StrEnum imports
        lines = [l for l in lines if 'from enum import StrEnum' not in l]
        
        # Replace class X(str, Enum) with StrEnum
        for i, l in enumerate(lines):
            import re
            if re.search(r'class \w+\(str,\s*(?:enum\.)?Enum\):', l):
                lines[i] = re.sub(r'class (\w+)\(str,\s*(?:enum\.)?Enum\):', r'class \1(StrEnum):', l)

        # find insert pos
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('from __future__ import'):
                insert_idx = i + 1
                break
                
        if insert_idx == 0:
            if lines and lines[0].startswith('"""'):
                for i, line in enumerate(lines[1:]):
                    if line.strip() == '"""':
                        insert_idx = i + 2
                        break
        
        if insert_idx == 0 and lines and lines[0].startswith('#'):
            for i, line in enumerate(lines):
                if not line.startswith('#'):
                    insert_idx = i
                    break

        lines.insert(insert_idx, 'from enum import StrEnum\n')
        
        with open(filepath, 'w') as f:
            f.writelines(lines)
    except Exception as e:
        print(e)

print("Cleaned StrEnum imports.")
