import re
from pathlib import Path
import os

for f in Path("apps/backend/src").rglob("*.py"):
    with open(f, "r") as file:
        content = file.read()
    
    if "StrEnum" in content and "from enum import" not in content and "import enum" not in content:
        # inject after docstring
        if content.startswith('"""'):
            end_quote = content.find('"""', 3)
            if end_quote != -1:
                content = content[:end_quote+3] + "\nfrom enum import StrEnum\n" + content[end_quote+3:]
            else:
                content = "from enum import StrEnum\n" + content
        else:
            content = "from enum import StrEnum\n" + content
            
        with open(f, "w") as file:
            file.write(content)
        print(f"Fixed missing StrEnum import in {f}")
        
