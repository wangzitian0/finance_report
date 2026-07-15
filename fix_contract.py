with open("common/platform/contract.py", "r") as f:
    content = f.read()

import re
# Regex to match the ACRecord with status="dropped"
# ACRecord(
#     id="AC-platform.12...",
#     ...
#     status="dropped",
# ),
content = re.sub(r'\s*ACRecord\(\s*id="AC-platform\.12\.[^"]+",\s*epic=12,\s*epic_name="foundation-libs",\s*description="[^"]+",\s*mandatory=False,\s*status="dropped",\s*\),', '', content)

with open("common/platform/contract.py", "w") as f:
    f.write(content)
