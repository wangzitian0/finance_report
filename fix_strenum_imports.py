import glob

for filepath in glob.glob('apps/backend/src/**/*.py', recursive=True):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    if not lines or 'from enum import StrEnum' not in lines[0]:
        continue
        
    lines.pop(0) # remove from top
    
    # find where to insert
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith('from __future__ import'):
            insert_idx = i + 1
            break
            
    if insert_idx == 0:
        # no future import, look for docstring end
        if lines and lines[0].startswith('"""'):
            for i, line in enumerate(lines[1:]):
                if line.strip() == '"""':
                    insert_idx = i + 2
                    break
                    
    lines.insert(insert_idx, 'from enum import StrEnum\n')
    
    with open(filepath, 'w') as f:
        f.writelines(lines)

print("Fixed StrEnum import locations.")
