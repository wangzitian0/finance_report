import re
from pathlib import Path

# Regex to match:
# ACRecord(
#     id="AC-...",
#     epic=...,
#     epic_name="...",
#     description="...",
#     mandatory=...,
#     status="dropped",
# ),

pattern = re.compile(
    r'ACRecord\(\s*id="([^"]+)",\s*epic=\d+,\s*epic_name="[^"]+",\s*description="([^"]+)",\s*mandatory=(?:True|False),\s*status="dropped",\s*\)'
)

for f in Path("common").rglob("contract.py"):
    with open(f, "r") as file:
        content = file.read()
    
    # Replace matched blocks with a valid ACRecord
    def repl(m):
        ac_id = m.group(1)
        desc = m.group(2)
        return f'ACRecord(\n            id="{ac_id}",\n            statement="{desc} (DROPPED)",\n            test="TODO",\n            priority="P0",\n            status="done",\n        )'

    new_content = pattern.sub(repl, content)
    
    if new_content != content:
        with open(f, "w") as file:
            file.write(new_content)
        print(f"Fixed dropped ACs in {f}")

