"""Render the package governance control projection without inventing state."""

from __future__ import annotations


def render_governance_markdown(index: dict[str, object]) -> str:
    initiatives = index["initiatives"]
    guarantees = index["guarantees"]
    lines = [
        "# Package Governance",
        "",
        "| Package | Initiative | Current / target | Open | Blocked | State | Issue |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for initiative_id in sorted(initiatives):
        row = initiatives[initiative_id]
        lines.append(
            f"| {row['package']} | {row['title']} | {row['current']} / {row['target']} | "
            f"{row['open_guarantees']} | {row['blocked_guarantees']} | {row['state']} | "
            f"{row['issue']} |"
        )

    census = index.get("census") or index.get("denominators")
    if isinstance(census, dict):
        delivery = census.get("delivery_surfaces", {})
        roots = census.get("backend_root_modules", {})
        units = census.get("ddd_units", {})
        ops = census.get("operations", {})
        fe = census.get("frontend_assets", {})
        lines.extend(
            [
                "",
                "## Exhaustive Governance Denominators",
                "",
                "| Asset Surface | Count | Category / Status |",
                "|---|---:|---|",
                f"| Flat Routers (`apps/backend/src/routers/`) | {delivery.get('router_count', 0)} | Sanctioned delivery debt (shrink-only ratchet) |",
                f"| Flat Schemas (`apps/backend/src/schemas/`) | {delivery.get('schema_count', 0)} | Sanctioned DTO debt (shrink-only ratchet) |",
                f"| Backend Root Modules (`apps/backend/src/`) | {roots.get('count', 0)} | Shell & composition boundaries |",
                f"| Total DDD Units | {units.get('total_count', 0)} | Package-owned domain building blocks |",
                f"| Bound DDD Units | {units.get('bound_count', 0)} | Implemented building blocks |",
                f"| Unbound DDD Units | {units.get('unbound_count', 0)} | Migration debt (shrink-only ratchet) |",
                f"| Incomplete Repository Splits | {units.get('incomplete_splits', 0)} | Migration debt (shrink-only ratchet) |",
                f"| OpenAPI Operations (Total) | {ops.get('total_operations', 0)} | Backend REST endpoints |",
                f"| Consumed Operations | {ops.get('consumed_operations', 0)} | Consumed via direct or semantic client wrapper |",
                f"| Intentional API-Only Operations | {ops.get('api_only_operations', 0)} | Intentional non-UI API capabilities |",
                f"| Frontend Consumer Call Sites | {ops.get('total_consumer_call_sites', 0)} | Generated & semantic operation consumers |",
                f"| Frontend Production Files | {fe.get('production_file_count', 0)} | Production TS/TSX asset census |",
            ]
        )

    for initiative_id in sorted(initiatives):
        row = initiatives[initiative_id]
        lines.extend(["", f"## {initiative_id}", ""])
        for guarantee_id in row["guarantees"]:
            guarantee = guarantees[guarantee_id]
            proof = guarantee["proof"] or {}
            enforcement = guarantee["enforcement"] or {}
            context = enforcement.get("required_context") or "missing"
            lines.extend(
                [
                    f"### {guarantee_id}",
                    f"- State: {guarantee['state']}",
                    f"- ACs: {', '.join(guarantee['affected_acs'])}",
                    f"- Tests: {', '.join(guarantee['test_refs'])}",
                    f"- Proof: {proof.get('target_sha', 'missing')} / {proof.get('result', 'missing')} / {proof.get('occurred_at', 'missing')}",
                    f"- Evidence: {proof.get('evidence_url', 'missing')}",
                    f"- Enforcement: {proof.get('gate_id', 'missing')} -> {context}",
                ]
            )
            for finding in guarantee["findings"]:
                lines.append(f"- Finding `{finding['code']}`: {finding['message']}")
    return "\n".join(lines) + "\n"


__all__ = ["render_governance_markdown"]
