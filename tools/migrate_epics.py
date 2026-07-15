import os
import re

EPICS_DIR = "docs/project"
COMMON_DIR = "common"

MAPPING = {
    "AC1.10.4": "ui_core",
    "AC4.8.1": "reconciliation",
    "AC4.10.3": "reconciliation",
    "AC5.37.2": "reporting",
    "AC6.34.1": "advisor",
    "AC7.1.1": "runtime",
    "AC7.1.2": "runtime",
    "AC7.1.3": "runtime",
    "AC7.2.1": "runtime",
    "AC7.2.2": "runtime",
    "AC7.2.3": "runtime",
    "AC7.2.4": "runtime",
    "AC7.2.5": "runtime",
    "AC7.3.1": "runtime",
    "AC7.3.2": "runtime",
    "AC7.3.3": "runtime",
    "AC7.3.4": "runtime",
    "AC7.3.5": "runtime",
    "AC7.4.1": "runtime",
    "AC7.4.2": "runtime",
    "AC7.4.3": "runtime",
    "AC7.4.4": "runtime",
    "AC7.4.5": "runtime",
    "AC7.4.6": "runtime",
    "AC7.5.1": "runtime",
    "AC7.5.2": "runtime",
    "AC7.5.3": "runtime",
    "AC7.5.4": "runtime",
    "AC7.5.5": "runtime",
    "AC7.6.2": "runtime",
    "AC7.9.1": "runtime",
    "AC7.9.2": "runtime",
    "AC7.9.3": "runtime",
    "AC7.9.4": "runtime",
    "AC7.9.5": "runtime",
    "AC7.9.6": "runtime",
    "AC8.13.61": "testing",
    "AC8.13.62": "testing",
    "AC8.13.63": "testing",
    "AC12.22.1": "platform",
    "AC12.22.2": "platform",
    "AC12.24.1": "platform",
    "AC12.24.2": "platform",
    "AC12.24.3": "platform",
    "AC12.25.1": "platform",
    "AC15.7.8": "ui_core",
    "AC16.1.2": "ui_core",
    "AC16.23.1": "ui_core",
    "AC16.23.2": "ui_core",
    "AC16.23.5": "ui_core",
    "AC16.11.32": "ui_core",
    "AC17.7.6": "portfolio",
    "AC19.11.1": "ui_core",
    "AC21.1.1": "advisor",
    "AC26.9.1": "meta",
}

def parse_ac(line):
    # Table row format: | AC7.4.6 | Statement | Test | Path | Priority | <!-- epic-owned: horizontal -->
    table_match = re.match(r'\|\s*(AC\d+\.\d+(?:\.\d+)?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|.*?\|\s*(P[0-3]|🔴.*?)\s*\|', line)
    if table_match:
        ac_id = table_match.group(1).strip()
        statement = table_match.group(2).strip()
        test = table_match.group(3).strip()
        priority = table_match.group(4).strip()
        if priority.startswith("🔴"):
            priority = "P0"
        return {
            "id": f"AC-{MAPPING.get(ac_id, 'unknown')}.{ac_id[2:]}",
            "statement": statement,
            "test": test,
            "priority": priority,
            "status": "done",
            "pkg": MAPPING.get(ac_id, "unknown")
        }
    
    # List format: - [x] **AC16.23.1** Statement <!-- epic-owned: fe-only -->
    list_match = re.match(r'-\s*\[(x| )\]\s*\*\*(AC\d+\.\d+(?:\.\d+)?)\*\*\s*(.*?)\s*<!--', line)
    if list_match:
        status = "done" if list_match.group(1).lower() == "x" else "open"
        ac_id = list_match.group(2).strip()
        statement = list_match.group(3).strip()
        return {
            "id": f"AC-{MAPPING.get(ac_id, 'unknown')}.{ac_id[2:]}",
            "statement": statement,
            "test": "Manual UI test",
            "priority": "P1",
            "status": status,
            "pkg": MAPPING.get(ac_id, "unknown")
        }
    
    return None

def main():
    acs_by_pkg = {}
    
    for filename in os.listdir(EPICS_DIR):
        if not filename.startswith("EPIC-") or not filename.endswith(".md"):
            continue
        filepath = os.path.join(EPICS_DIR, filename)
        with open(filepath, "r") as f:
            lines = f.readlines()
            
        new_lines = []
        modified = False
        
        for line in lines:
            if "epic-owned" in line:
                ac_data = parse_ac(line)
                if ac_data:
                    pkg = ac_data["pkg"]
                    if pkg not in acs_by_pkg:
                        acs_by_pkg[pkg] = []
                    acs_by_pkg[pkg].append(ac_data)
                    modified = True
                    continue # exclude from new_lines
                else:
                    # check if we can parse it anyway
                    print(f"Could not parse line: {line.strip()}")
            new_lines.append(line)
            
        if modified:
            with open(filepath, "w") as f:
                f.writelines(new_lines)
                
            # If empty or just a few lines left, delete it?
            if len(new_lines) < 10:
                content = "".join(new_lines).strip()
                if not content or content.startswith("#"):
                    print(f"Deleting empty EPIC: {filepath}")
                    os.remove(filepath)
                    
    # Now write to contracts
    for pkg, acs in acs_by_pkg.items():
        contract_path = os.path.join(COMMON_DIR, pkg, "contract.py")
        if not os.path.exists(contract_path):
            print(f"Warning: {contract_path} does not exist!")
            continue
            
        with open(contract_path, "r") as f:
            content = f.read()
            
        # Find roadmap=[
        roadmap_str = "roadmap=[\n"
        for ac in acs:
            # Escape quotes
            stmt = ac["statement"].replace('"', '\\"')
            tst = ac["test"].replace('"', '\\"')
            roadmap_str += f"""        ACRecord(
            id="{ac['id']}",
            statement="{stmt}",
            test="{tst}",
            priority="{ac['priority']}",
            status="{ac['status']}",
        ),
"""
        
        if "roadmap=[\n" in content:
            new_content = content.replace("roadmap=[\n", roadmap_str)
        elif "roadmap=[]" in content:
            new_content = content.replace("roadmap=[]", roadmap_str + "    ]")
        else:
            print(f"Could not find roadmap in {contract_path}")
            continue
            
        with open(contract_path, "w") as f:
            f.write(new_content)
        print(f"Added {len(acs)} ACs to {contract_path}")

if __name__ == "__main__":
    main()
