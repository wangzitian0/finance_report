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
        content = file.read()
    if 'StrEnum' in content and 'import StrEnum' not in content and 'StrEnum,' not in content and ', StrEnum' not in content:
        if 'from enum import Enum' in content:
            content = content.replace('from enum import Enum', 'from enum import Enum, StrEnum')
        else:
            content = 'from enum import Enum, StrEnum\n' + content
        with open(f, 'w') as file:
            file.write(content)
        print(f"Fixed {f}")
