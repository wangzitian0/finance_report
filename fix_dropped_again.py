import re
from pathlib import Path

for f in Path("common").rglob("contract.py"):
    with open(f, "r") as file:
        content = file.read()
    
    # We want to remove blocks starting with ACRecord( and ending with status="dropped",\n        ), or similar
    # Let's just find "status=\"dropped\"" and then expand out to the matching ACRecord
    
    while True:
        idx = content.find('status="dropped"')
        if idx == -1:
            break
            
        start = content.rfind("ACRecord(", 0, idx)
        end = content.find("),", idx)
        if end != -1:
            end += 2
        else:
            end = content.find(")", idx) + 1
            
        # remove from start to end
        content = content[:start] + content[end:]
        print(f"Removed a dropped AC in {f}")

    with open(f, "w") as file:
        file.write(content)

