import re
from pathlib import Path

# Match: class Name(str, Enum):
# Need to change to: class Name(StrEnum):
# And add: from enum import StrEnum

pattern = re.compile(r'class\s+([A-Za-z0-9_]+)\(str,\s*Enum\):')

for f in Path("apps/backend/src").rglob("*.py"):
    with open(f, "r") as file:
        content = file.read()
    
    if "(str, Enum)" in content:
        content = pattern.sub(r'class \1(StrEnum):', content)
        
        # we need to make sure StrEnum is imported
        if "StrEnum" not in content:
            # find where `from enum import ` is
            if "from enum import " in content:
                content = content.replace("from enum import ", "from enum import StrEnum, ")
            else:
                content = "from enum import StrEnum\n" + content
                
        with open(f, "w") as file:
            file.write(content)
        print(f"Fixed {f}")

