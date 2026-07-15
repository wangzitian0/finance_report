
# Mapping of missing AC IDs to their destination packages
# Let's map them all
MISSING_ACS = {
    "AC12.24.1": "observability",
    "AC12.25.1": "platform",
    "AC15.7.8": "reconciliation",
    "AC16.23.1": "ui_core",
    "AC19.11.1": "ui_core",
    "AC26.9.1": "runtime",
    "AC4.10.3": "reconciliation",
    "AC5.37.2": "reporting",
    "AC6.34.1": "advisor",
    "AC-testing.8.13": "testing", # Actually this one is a bit weird, let's look at EPIC-008
}

print("Running script")
