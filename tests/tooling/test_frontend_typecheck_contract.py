import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_AC8_13_99_frontend_typecheck_is_a_required_gate() -> None:
    """AC8.13.99: Frontend tests and CI run full TypeScript checking."""

    package_json = json.loads(read("apps/frontend/package.json"))
    assert package_json["scripts"]["typecheck"] == "tsc --noEmit"

    cli = read("tools/_lib/dev/cli.py")
    assert 'run(["npm", "run", "typecheck"], cwd=FRONTEND_DIR)' in cli

    workflow = read(".github/workflows/ci.yml")
    frontend_block = workflow.split("  frontend:", 1)[1].split(
        "  container-images:", 1
    )[0]
    assert "Run Frontend Type Check" in frontend_block
    assert "npm run typecheck" in frontend_block
