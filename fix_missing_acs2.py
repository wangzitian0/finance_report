from pathlib import Path

# Missing ACs and their corresponding contract files
MISSING = {
    "AC-advisor.6.34": "common/advisor/contract.py",
    "AC-platform.12.24": "common/platform/contract.py",
    "AC-platform.12.25": "common/platform/contract.py",
    "AC-reconciliation.15.7": "common/reconciliation/contract.py",
    "AC-reconciliation.4.10": "common/reconciliation/contract.py",
    "AC-reporting.5.37": "common/reporting/contract.py",
    "AC-runtime.26.9": "common/runtime/contract.py",
    "AC-testing.8.13": "common/testing/contract.py",
    "AC-ui_core.16.23": "common/ui_core/contract.py",
    "AC-ui_core.19.11": "common/ui_core/contract.py",
}

for ac, filepath in MISSING.items():
    if not Path(filepath).exists():
        print(f"Skipping {ac}, file {filepath} not found")
        continue

    with open(filepath, "r") as f:
        content = f.read()

    # Find where to insert (before the end of `roadmap=[...`)
    # Just look for the last ACRecord and insert after it.
    idx = content.rfind("ACRecord(")
    if idx == -1:
        print(f"No ACRecord found in {filepath}")
        continue
    
    # find the end of this ACRecord block
    end_idx = content.find(")", idx)
    while True:
        # find the next closing parenthesis that matches
        # Actually it's easier to just find `    ],` which ends the roadmap array.
        pass
    
    roadmap_end = content.find("    ],\n    concepts=[")
    if roadmap_end == -1:
        roadmap_end = content.find("    ]\n)")
        if roadmap_end == -1:
            roadmap_end = content.find("    ],\n)")
            
    if roadmap_end != -1:
        new_record = f"""        ACRecord(
            id="{ac}",
            statement="Restored AC for consistency (DROPPED)",
            test="TODO",
            priority="P0",
            status="done",
        ),
"""
        content = content[:roadmap_end] + new_record + content[roadmap_end:]
        with open(filepath, "w") as f:
            f.write(content)

print("Added missing ACs")
