import re
from pathlib import Path

ADDITIONS = {
    "platform": [
        ("AC-platform.12.24.1", "12", "foundation-libs", "metrics endpoint returns 200 OK (deferred)", "dropped", "horizontal"),
        ("AC-platform.12.24.2", "12", "foundation-libs", "metrics endpoint returns text/plain (deferred)", "dropped", "horizontal"),
        ("AC-platform.12.24.3", "12", "foundation-libs", "metrics response contains Prometheus data (deferred)", "dropped", "horizontal"),
        ("AC-platform.12.25.1", "12", "foundation-libs", "UUID logging formatting (doc-governance self-check)", "dropped", "horizontal"),
    ],
    "reconciliation": [
        ("AC-reconciliation.15.7.8", "15", "processing-account", "Reconciliation processing account check", "dropped", "horizontal"),
        ("AC-reconciliation.4.10.3", "4", "reconciliation-engine", "CI treats reconciliation audit JSON/Markdown as a hard gate", "dropped", "horizontal"),
    ],
    "ui_core": [
        ("AC-ui_core.16.23.1", "16", "two-stage-review-ui", "Two-stage review UI capability", "dropped", "horizontal"),
        ("AC-ui_core.19.11.1", "19", "event-driven-upload-to-report-ux", "Event-driven upload to report UX", "dropped", "horizontal"),
    ],
    "runtime": [
        ("AC-runtime.26.9.1", "26", "ac-authority-tiers", "Authority tier capability", "dropped", "horizontal"),
    ],
    "reporting": [
        ("AC-reporting.5.37.2", "5", "reporting-visualization", "Reporting visualization capability", "dropped", "horizontal"),
    ],
    "advisor": [
        ("AC-advisor.6.34.1", "6", "ai-advisor", "AI advisor capability", "dropped", "horizontal"),
    ],
    "testing": [
        ("AC-testing.8.13.61", "8", "testing-strategy", "Future observability, visual regression, and performance gates", "dropped", "horizontal"),
        ("AC-testing.8.13.62", "8", "testing-strategy", "Test observability", "dropped", "horizontal"),
        ("AC-testing.8.13.63", "8", "testing-strategy", "Performance testing", "dropped", "horizontal"),
    ]
}

def add_records(pkg, records):
    path = Path(f"common/{pkg}/contract.py")
    if not path.exists():
        print(f"File not found: {path}")
        return
    
    text = path.read_text()
    
    # find the end of roadmap=[...] array
    # We can use regex to find roadmap=[...]
    
    # Strategy: find "roadmap=[" then find the matching closing bracket
    match = re.search(r'roadmap=\[', text)
    if not match:
        print(f"roadmap not found in {pkg}")
        return
    
    start_idx = match.end()
    bracket_count = 1
    end_idx = start_idx
    for i in range(start_idx, len(text)):
        if text[i] == '[':
            bracket_count += 1
        elif text[i] == ']':
            bracket_count -= 1
            if bracket_count == 0:
                end_idx = i
                break
                
    if bracket_count != 0:
        print(f"Could not find matching bracket for roadmap in {pkg}")
        return
        
    records_str = ""
    for r in records:
        records_str += f"""
        ACRecord(
            id="{r[0]}",
            epic={r[1]},
            epic_name="{r[2]}",
            description="{r[3]}",
            mandatory=False,
            status="{r[4]}",
        ),
"""
    
    new_text = text[:end_idx] + records_str + "    " + text[end_idx:]
    path.write_text(new_text)
    print(f"Added {len(records)} records to {pkg}")

for pkg, records in ADDITIONS.items():
    add_records(pkg, records)
