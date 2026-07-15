import re
from pathlib import Path

f = Path("apps/backend/tests/api/test_api_surface_consistency.py")
with open(f, "r") as file:
    content = file.read()
    
# Remove `import src.routers as _routers_pkg`
content = content.replace("import src.routers as _routers_pkg\n", "")

# Replace _ROUTER_DIR
content = content.replace(
    "_ROUTER_DIR = Path(_routers_pkg.__file__).resolve().parent",
    "_SRC_DIR = Path(__file__).resolve().parent.parent.parent / 'src'"
)

content = content.replace(
    '_ROUTER_DIR.glob("*.py")',
    '_SRC_DIR.rglob("extension/api/*.py")'
)

with open(f, "w") as file:
    file.write(content)
print("Fixed test_api_surface_consistency.py")
