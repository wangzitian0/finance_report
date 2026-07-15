files = [
    "apps/backend/src/advisor/orm/chat.py",
    "apps/backend/src/extraction/extension/transaction_classification.py",
    "apps/backend/src/runtime/base/kind.py",
    "apps/backend/src/runtime/base/tiers.py"
]
for f in files:
    with open(f, 'r') as file:
        content = file.read()
    
    if 'import StrEnum' not in content:
        if 'from __future__ import annotations' in content:
            content = content.replace('from __future__ import annotations', 'from __future__ import annotations\nfrom enum import Enum, StrEnum')
        else:
            # find first import
            import_idx = content.find('import')
            if import_idx != -1:
                # find start of line
                line_start = content.rfind('\n', 0, import_idx) + 1
                content = content[:line_start] + 'from enum import Enum, StrEnum\n' + content[line_start:]
    
    # also remove any stray 'from enum import Enum, StrEnum' that is before __future__
    # just brute force remove it if it's the very first line
    if content.startswith('from enum import Enum, StrEnum\n'):
        content = content.replace('from enum import Enum, StrEnum\n', '', 1)

    with open(f, 'w') as file:
        file.write(content)

