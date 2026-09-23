from __future__ import annotations

import json
from pathlib import Path

from common.meta.extension.consumer_proofs import (
    ALL_PACKAGES,
    generate_consumer_proofs,
    main,
)


def test_generate_consumer_proofs_covers_all_packages(tmp_path: Path) -> None:
    """AC-runtime.env-empty-values.2: All bounded-context packages have verified consumer proofs."""
    proofs = generate_consumer_proofs()
    assert len(proofs) == len(ALL_PACKAGES)
    for pkg in ALL_PACKAGES:
        assert proofs.get(pkg) is not None
        assert proofs[pkg]["result"] == "passed"
        assert proofs[pkg]["strength"] == "exact"
        assert proofs[pkg]["proof"].startswith(f"proof-runtime-settings-compat-{pkg}")


def test_generate_consumer_proofs_handles_missing_package(tmp_path: Path) -> None:
    """Consumer proofs gracefully mark packages without contract.py as skipped."""
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "common" / "runtime").mkdir(parents=True)
    (fake_repo / "common" / "runtime" / "contract.py").write_text(
        "# contract\n", encoding="utf-8"
    )

    proofs = generate_consumer_proofs(repo_root=fake_repo)
    assert proofs["runtime"]["result"] == "passed"
    assert proofs["ledger"]["result"] == "skipped"


def test_consumer_proofs_main_entrypoint(tmp_path: Path) -> None:
    """Main CLI produces the expected JSON output file."""
    output_path = tmp_path / "proofs.json"
    exit_code = main(["--output", str(output_path)])
    assert exit_code == 0
    assert output_path.exists()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data.get("runtime") is not None
    assert data["runtime"]["result"] == "passed"
