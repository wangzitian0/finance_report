from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps/backend/src"
SERVICES = SRC / "services"

RESIDUE_MOVES = {
    "statement_parsing.py": SRC / "extraction/extension/statement_parsing.py",
    "statement_parsing_supervisor.py": SRC / "extraction/extension/statement_parsing_supervisor.py",
    "statement_pipeline.py": SRC / "extraction/extension/statement_pipeline.py",
    "statement_flow.py": SRC / "extraction/extension/statement_flow.py",
    "statement_validation.py": SRC / "extraction/extension/statement_validation.py",
    "statement_posting.py": SRC / "extraction/extension/statement_posting.py",
    "statement_workflow.py": SRC / "extraction/extension/statement_workflow.py",
    "brokerage_statement_payload.py": SRC / "extraction/extension/brokerage_statement_payload.py",
    "chain_repair.py": SRC / "extraction/extension/chain_repair.py",
    "classification.py": SRC / "extraction/extension/classification.py",
    "transaction_classification.py": SRC / "extraction/extension/transaction_classification.py",
    "correction_loop.py": SRC / "extraction/extension/correction_loop.py",
    "correction_service.py": SRC / "extraction/extension/correction_service.py",
    "review_queue.py": SRC / "extraction/extension/review_queue.py",
    "storage_sweep.py": SRC / "runtime/extension/storage_sweep.py",
    "workflow_events.py": SRC / "platform/extension/workflow_events.py",
    "workflow_event_builders.py": SRC / "platform/extension/workflow_event_builders.py",
    "accounting.py": SRC / "ledger/extension/accounting.py",
    "account_service.py": SRC / "ledger/extension/account_service.py",
    "account_coverage.py": SRC / "ledger/data/account_coverage.py",
    "fx_revaluation.py": SRC / "ledger/extension/fx_revaluation.py",
    "storage.py": SRC / "runtime/extension/storage.py",
    "source_type_priority.py": SRC / "audit/source_type_priority.py",
    "app_config.py": SRC / "config_app.py",
}

OLD_IMPORT_PATHS = {
    "src.services.statement_parsing",
    "src.services.statement_parsing_supervisor",
    "src.services.statement_pipeline",
    "src.services.statement_flow",
    "src.services.statement_validation",
    "src.services.statement_posting",
    "src.services.statement_workflow",
    "src.services.brokerage_statement_payload",
    "src.services.chain_repair",
    "src.services.classification",
    "src.services.transaction_classification",
    "src.services.correction_loop",
    "src.services.correction_service",
    "src.services.review_queue",
    "src.services.source_type_priority",
    "src.services.storage_sweep",
    "src.services.workflow_events",
    "src.services.workflow_event_builders",
    "src.services.accounting",
    "src.services.account_service",
    "src.services.account_coverage",
    "src.services.fx_revaluation",
    "src.services.storage",
    "src.services.app_config",
}


def test_stage2_residue_modules_left_services() -> None:
    for old_name, new_path in RESIDUE_MOVES.items():
        assert new_path.exists(), f"missing migrated module: {new_path.relative_to(REPO)}"
        assert not (SERVICES / old_name).exists(), f"legacy services residue remains: {old_name}"


def test_stage2_residue_old_service_imports_are_gone() -> None:
    offenders: list[str] = []
    for path in REPO.rglob("*.py"):
        if ".venv" in path.parts or ".claude" in path.parts:
            # .claude/ is the agent runtime/config dir: its committed content
            # carries no Python, and its gitignored worktrees/ subdir holds
            # local copies of old checkouts whose imports would otherwise be
            # reported as residue that is not in the repo.
            continue
        if path == Path(__file__):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module in OLD_IMPORT_PATHS:
                    offenders.append(f"{path.relative_to(REPO)} -> {module}")
    assert not offenders, "old service imports remain:\n" + "\n".join(sorted(offenders))


def test_stage2_residue_docs_and_comments_use_current_paths() -> None:
    stale_extraction_path = "apps/backend/src/services/extraction/"
    current_extraction_path = "apps/backend/src/extraction/"
    extraction_readme = (REPO / "common/extraction/readme.md").read_text(encoding="utf-8")
    assert stale_extraction_path not in extraction_readme
    assert current_extraction_path in extraction_readme

    stale_llm_path = "src/llm/common"
    for relpath in (
        "apps/backend/migrations/versions/0043_llm_provider_config.py",
        "apps/backend/src/config.py",
        "apps/backend/src/llm/orm/config.py",
        "apps/backend/src/schemas/llm.py",
    ):
        text = (REPO / relpath).read_text(encoding="utf-8")
        assert stale_llm_path not in text, f"stale llm/common path remains in {relpath}"
