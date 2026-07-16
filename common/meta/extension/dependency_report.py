"""Dependency topology and public-boundary impact reporting.

This extension owns filesystem, AST, and Git-ref I/O. The dependency graph
itself remains a pure ``base`` computation so both this report and the ``data``
projection use one policy implementation.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from common.meta.base.dependency_graph import build_dependency_graph
from common.meta.extension.check_package_contract import (
    DiscoveredPackage,
    discover_packages,
)


def _annotation(node: ast.expr | None) -> str:
    return ast.unparse(node) if node is not None else "Any"


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix}({ast.unparse(node.args)}) -> {_annotation(node.returns)}"


def _class_signature(node: ast.ClassDef) -> str:
    bases = ", ".join(ast.unparse(base) for base in node.bases)
    members: list[str] = []
    for child in node.body:
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            members.append(f"{child.target.id}: {_annotation(child.annotation)}")
        elif isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and not child.name.startswith("_"):
            signature = _function_signature(child)
            suffix = signature.removeprefix("async def").removeprefix("def")
            members.append(f"{child.name}{suffix}")
    body = "; ".join(members)
    return f"class({bases}){{{body}}}"


def _definition_signatures(
    impl_dir: Path, repo_root: Path
) -> dict[str, list[tuple[str, int, str]]]:
    definitions: dict[str, list[tuple[str, int, str]]] = {}
    for source in sorted(impl_dir.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        relative = source.relative_to(repo_root).as_posix()
        for node in tree.body:
            name: str | None = None
            signature: str | None = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                signature = _function_signature(node)
            elif isinstance(node, ast.ClassDef):
                name = node.name
                signature = _class_signature(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                signature = f"value: {_annotation(node.annotation)}"
            elif isinstance(node, ast.Assign):
                names = [
                    target.id for target in node.targets if isinstance(target, ast.Name)
                ]
                if len(names) == 1:
                    name = names[0]
                    signature = f"value={ast.unparse(node.value)}"
            if name is not None and signature is not None:
                definitions.setdefault(name, []).append(
                    (relative, node.lineno, signature)
                )
    return definitions


def _root_reexport(impl_dir: Path, symbol: str) -> str | None:
    init_path = impl_dir / "__init__.py"
    if not init_path.is_file():
        return None
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            public_name = alias.asname or alias.name
            if public_name == symbol:
                module = "." * node.level + (node.module or "")
                return f"reexport:{module}.{alias.name}"
    return None


def _public_symbol_records(
    package: DiscoveredPackage, repo_root: Path
) -> list[dict[str, str]]:
    if not package.contract.interface:
        return []
    if package.impl_dir is None or not package.impl_dir.is_dir():
        raise RuntimeError(
            f"package {package.name!r} publishes an interface but has no readable "
            "BE implementation"
        )

    definitions = _definition_signatures(package.impl_dir, repo_root)
    records: list[dict[str, str]] = []
    for symbol in sorted(package.contract.interface):
        matches = definitions.get(symbol, [])
        if matches:
            signatures = sorted({signature for _, _, signature in matches})
            sources = sorted({source for source, _, _ in matches})
            records.append(
                {
                    "package": package.name,
                    "symbol": symbol,
                    "signature": " | ".join(signatures),
                    "resolution": "definition" if len(matches) == 1 else "ambiguous",
                    "source": ",".join(sources),
                }
            )
            continue

        reexport = _root_reexport(package.impl_dir, symbol)
        records.append(
            {
                "package": package.name,
                "symbol": symbol,
                "signature": reexport or "dynamic-export",
                "resolution": "reexport" if reexport else "dynamic",
                "source": package.impl_dir.joinpath("__init__.py")
                .relative_to(repo_root)
                .as_posix(),
            }
        )
    return records


def build_dependency_snapshot(repo_root: Path) -> dict[str, object]:
    """Build a deterministic dependency/public-boundary snapshot of a tree."""

    root = repo_root.resolve()
    packages = discover_packages(root)
    if not packages:
        raise RuntimeError(f"no package contracts discovered under {root}")

    graph = build_dependency_graph([package.contract for package in packages])
    public_symbols = [
        record
        for package in sorted(packages, key=lambda item: item.name)
        for record in _public_symbol_records(package, root)
    ]
    snapshot = graph.as_dict()
    snapshot["public_symbols"] = public_symbols
    return snapshot


def _edge_key(edge: dict[str, str]) -> tuple[str, str, str, str]:
    return (edge["consumer"], edge["provider"], edge["kind"], edge["detail"])


def _symbol_map(snapshot: dict[str, object]) -> dict[tuple[str, str], dict[str, str]]:
    records = snapshot["public_symbols"]
    assert isinstance(records, list)
    return {
        (record["package"], record["symbol"]): record
        for record in records
        if isinstance(record, dict)
    }


def _consumer_set(
    snapshots: Iterable[dict[str, object]], package: str, field: str
) -> list[str]:
    consumers: set[str] = set()
    for snapshot in snapshots:
        index = snapshot[field]
        assert isinstance(index, dict)
        values = index.get(package, [])
        assert isinstance(values, list)
        consumers.update(value for value in values if isinstance(value, str))
    return sorted(consumers)


def compare_dependency_snapshots(
    base: dict[str, object], head: dict[str, object]
) -> dict[str, object]:
    """Compare two snapshots and compute the complete consumer fan-out."""

    base_edges = {_edge_key(edge): edge for edge in base["edges"]}  # type: ignore[index]
    head_edges = {_edge_key(edge): edge for edge in head["edges"]}  # type: ignore[index]
    added_edges = [head_edges[key] for key in sorted(head_edges.keys() - base_edges)]
    removed_edges = [base_edges[key] for key in sorted(base_edges.keys() - head_edges)]

    base_symbols = _symbol_map(base)
    head_symbols = _symbol_map(head)
    added_symbols = [
        head_symbols[key] for key in sorted(head_symbols.keys() - base_symbols)
    ]
    removed_symbols = [
        base_symbols[key] for key in sorted(base_symbols.keys() - head_symbols)
    ]
    changed_symbols: list[dict[str, str]] = []
    for key in sorted(base_symbols.keys() & head_symbols):
        before = base_symbols[key]
        after = head_symbols[key]
        if before["signature"] != after["signature"]:
            changed_symbols.append(
                {
                    "package": key[0],
                    "symbol": key[1],
                    "before": before["signature"],
                    "after": after["signature"],
                }
            )

    affected_packages = {
        record["package"]
        for record in (*added_symbols, *removed_symbols, *changed_symbols)
    }
    affected_packages.update(edge["provider"] for edge in added_edges)
    affected_packages.update(edge["provider"] for edge in removed_edges)

    affected_consumers: dict[str, dict[str, list[str]]] = {}
    for package in sorted(affected_packages):
        direct = _consumer_set((base, head), package, "direct_consumers")
        transitive = _consumer_set((base, head), package, "transitive_consumers")
        affected_consumers[package] = {
            "direct": direct,
            "transitive": transitive,
            "indirect": sorted(set(transitive) - set(direct)),
        }

    return {
        "base": base,
        "head": head,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "added_public_symbols": added_symbols,
        "removed_public_symbols": removed_symbols,
        "changed_public_symbols": changed_symbols,
        "affected_consumers": affected_consumers,
        "errors": [],
    }


def _snapshot_git_ref(repo_root: Path, ref: str) -> dict[str, object]:
    try:
        archive = subprocess.run(
            ["git", "-C", str(repo_root), "archive", "--format=tar", ref],
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cannot read base ref {ref!r}: {detail}") from exc

    with tempfile.TemporaryDirectory(prefix="ddd-dependency-base-") as temp_dir:
        base_root = Path(temp_dir)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            tar.extractall(base_root, filter="data")
        return build_dependency_snapshot(base_root)


def build_impact_report(repo_root: Path, *, base_ref: str) -> dict[str, object]:
    """Compare the working tree with an archive isolated from ``base_ref``."""

    root = repo_root.resolve()
    head = build_dependency_snapshot(root)
    base = _snapshot_git_ref(root, base_ref)
    report = compare_dependency_snapshots(base, head)
    report["base_ref"] = base_ref
    return report


def render_markdown(report: dict[str, object]) -> str:
    """Render the high-level dependency impact for a CI step summary."""

    added_edges = report["added_edges"]
    removed_edges = report["removed_edges"]
    added_symbols = report["added_public_symbols"]
    removed_symbols = report["removed_public_symbols"]
    changed_symbols = report["changed_public_symbols"]
    affected = report["affected_consumers"]
    assert isinstance(added_edges, list)
    assert isinstance(removed_edges, list)
    assert isinstance(added_symbols, list)
    assert isinstance(removed_symbols, list)
    assert isinstance(changed_symbols, list)
    assert isinstance(affected, dict)

    lines = [
        "## DDD Dependency Impact",
        "",
        f"Base: `{report.get('base_ref', 'snapshot')}`",
        "",
        "| Change | Count |",
        "|---|---:|",
        f"| Added dependency edges | {len(added_edges)} |",
        f"| Removed dependency edges | {len(removed_edges)} |",
        f"| Added public symbols | {len(added_symbols)} |",
        f"| Removed public symbols | {len(removed_symbols)} |",
        f"| Changed public signatures | {len(changed_symbols)} |",
        f"| Affected provider packages | {len(affected)} |",
    ]
    edge_changes = [
        ("added", edge) for edge in added_edges if isinstance(edge, dict)
    ] + [("removed", edge) for edge in removed_edges if isinstance(edge, dict)]
    if edge_changes:
        lines.extend(
            [
                "",
                "### Dependency Edge Changes",
                "",
                "| Change | Consumer | Provider | Kind |",
                "|---|---|---|---|",
            ]
        )
        for change, edge in edge_changes:
            lines.append(
                f"| {change} | `{edge['consumer']}` | `{edge['provider']}` | "
                f"`{edge['kind']}` |"
            )

    boundary_changes: list[tuple[str, dict[str, str]]] = [
        ("added", record) for record in added_symbols if isinstance(record, dict)
    ]
    boundary_changes.extend(
        ("removed", record) for record in removed_symbols if isinstance(record, dict)
    )
    boundary_changes.extend(
        ("changed", record) for record in changed_symbols if isinstance(record, dict)
    )
    if boundary_changes:
        lines.extend(
            [
                "",
                "### Public Boundary Changes",
                "",
                "| Change | Package | Symbol | Before | After |",
                "|---|---|---|---|---|",
            ]
        )
        for change, record in boundary_changes:
            before = str(
                record.get(
                    "before", "-" if change == "added" else record.get("signature", "-")
                )
            )
            after = str(
                record.get(
                    "after",
                    "-" if change == "removed" else record.get("signature", "-"),
                )
            )
            before = before.replace("|", "\\|")
            after = after.replace("|", "\\|")
            lines.append(
                f"| {change} | `{record['package']}` | `{record['symbol']}` | "
                f"`{before}` | `{after}` |"
            )
    if affected:
        lines.extend(
            [
                "",
                "### Affected Consumers",
                "",
                "| Provider | Direct consumers | Indirect consumers |",
                "|---|---|---|",
            ]
        )
        for package, consumers in sorted(affected.items()):
            assert isinstance(consumers, dict)
            direct = ", ".join(consumers["direct"]) or "-"
            indirect = ", ".join(consumers["indirect"]) or "-"
            lines.append(f"| `{package}` | {direct} | {indirect} |")
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)

    report = build_impact_report(args.repo_root, base_ref=args.base_ref)
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    if args.json_out:
        _write(args.json_out, json_text)
    if args.markdown_out:
        _write(args.markdown_out, markdown)
    if not args.json_out and not args.markdown_out:
        print(json_text, end="")
    return 0
