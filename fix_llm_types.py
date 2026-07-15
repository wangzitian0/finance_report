import os
from pathlib import Path

# 1. Rename types.py to types/core.py
os.system('git mv apps/backend/src/llm/base/types.py apps/backend/src/llm/base/types/core.py')

# 2. Update imports
files = list(Path('apps/backend/src').rglob('*.py'))

for f in files:
    with open(f, 'r') as file:
        content = file.read()
    
    # We want to replace `from src.llm.base.types import` to `from src.llm.base.types.core import`
    # BUT wait! `from src.llm.base.types.llm import` also starts with `from src.llm.base.types`!
    # So we should only replace `from src.llm.base.types import`
    
    new_content = content.replace('from src.llm.base.types import', 'from src.llm.base.types.core import')
    if new_content != content:
        with open(f, 'w') as file:
            file.write(new_content)

