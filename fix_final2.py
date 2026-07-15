files = [
    "apps/backend/src/runtime/base/kind.py",
    "apps/backend/src/runtime/base/tiers.py",
    "apps/backend/src/advisor/orm/chat.py"
]


for f in files:
    with open(f, 'r') as file:
        content = file.read()
    
    if f.endswith('chat.py'):
        content = content.replace('from enum import Enum, StrEnum', 'from enum import StrEnum')
    else:
        content = content.replace('from enum import StrEnum\n\n', '')
        content = content.replace('from __future__ import annotations\n', 'from __future__ import annotations\nfrom enum import StrEnum\n')
        
    with open(f, 'w') as file:
        file.write(content)
        
