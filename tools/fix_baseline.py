import json
import pathlib
baseline = pathlib.Path("common/meta/data/epic-residue-baseline.json")
data = json.loads(baseline.read_text())
for k in data["files"]:
    data["files"][k] = {}
baseline.write_text(json.dumps(data, indent=2) + "\n")
