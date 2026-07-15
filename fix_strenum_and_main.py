import re

files_with_error = [
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

for filepath in files_with_error:
    with open(filepath, 'r') as f:
        content = f.read()
    if 'StrEnum' in content and 'from enum import StrEnum' not in content:
        # replace `import enum` with `from enum import StrEnum` if present
        if 'import enum' in content:
            content = content.replace('import enum', 'from enum import StrEnum')
        else:
            # insert after from __future__ or docstring
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('from __future__'):
                    continue
                if line.startswith('"""'):
                    continue
                lines.insert(i, 'from enum import StrEnum')
                break
            content = '\n'.join(lines)
        with open(filepath, 'w') as f:
            f.write(content)

with open('apps/backend/src/main.py', 'r') as f:
    main_content = f.read()

# Remove duplicate imports in main.py
main_content = re.sub(
    r'from src\.platform\.base\.types\.errors import \(\n\s*COMMON_ERROR_RESPONSES,\n\s*ErrorCode,\n\s*ErrorResponse,\n\s*error_code_for_status,\n\)',
    '',
    main_content,
    flags=re.MULTILINE
)

with open('apps/backend/src/main.py', 'w') as f:
    f.write(main_content)

print("Fixed StrEnum and main.py.")
