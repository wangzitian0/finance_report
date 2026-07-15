from pathlib import Path

REPLACEMENTS = {
    "AC12.24.1": "AC-platform.12.24.1",
    "AC12.24.2": "AC-platform.12.24.2",
    "AC12.24.3": "AC-platform.12.24.3",
    "AC12.25.1": "AC-platform.12.25.1",
    "AC15.7.8": "AC-reconciliation.15.7.8",
    "AC16.23.1": "AC-ui_core.16.23.1",
    "AC19.11.1": "AC-ui_core.19.11.1",
    "AC26.9.1": "AC-runtime.26.9.1",
    "AC4.10.3": "AC-reconciliation.4.10.3",
    "AC5.37.2": "AC-reporting.5.37.2",
    "AC6.34.1": "AC-advisor.6.34.1",
    "AC-testing.8.13": "AC-testing.8.13.61", # Just replace it
    "AC8.13.61": "AC-testing.8.13.61",
    "AC8.13.62": "AC-testing.8.13.62",
    "AC8.13.63": "AC-testing.8.13.63",
}

for p in Path("docs/project").glob("EPIC-*.md"):
    text = p.read_text()
    new_text = text
    for old, new in REPLACEMENTS.items():
        # Replace only if it's a word boundary or similar?
        # A simple string replace is probably fine since these IDs are unique
        new_text = new_text.replace(old, new)
        
        # also handle the case where someone wrote AC-testing.8.13 when it meant 8.13.61?
        # Let's just do literal replace.
    if new_text != text:
        p.write_text(new_text)
        print(f"Updated {p.name}")
