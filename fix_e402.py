import glob

# fix ui_core/__init__.py
with open('apps/backend/src/ui_core/__init__.py', 'w') as f:
    f.write('__all__ = ["app_config_router"]\nfrom .extension.api.app_config import router as app_config_router\n')

# fix other __init__.py files
for init_file in glob.glob('apps/backend/src/*/__init__.py'):
    with open(init_file, 'r') as f:
        lines = f.readlines()
    
    # Separate imports starting with "from .extension.api." and "from .base.types.errors"
    new_lines = []
    imports = []
    for line in lines:
        if line.startswith('from .extension.api.') or line.startswith('from .base.types.'):
            imports.append(line)
        else:
            new_lines.append(line)
            
    if not imports:
        continue
        
    # Insert imports right after "from __future__ import annotations" or at the top
    insert_idx = 0
    for i, line in enumerate(new_lines):
        if 'from __future__ import annotations' in line:
            insert_idx = i + 1
            break
            
    # if not found, check if there's a docstring
    if insert_idx == 0 and new_lines and new_lines[0].startswith('"""'):
        for i, line in enumerate(new_lines[1:]):
            if line.strip() == '"""':
                insert_idx = i + 2
                break
                
    final_lines = new_lines[:insert_idx] + imports + new_lines[insert_idx:]
    with open(init_file, 'w') as f:
        f.writelines(final_lines)

print("E402 fixed.")
