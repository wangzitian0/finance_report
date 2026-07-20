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
