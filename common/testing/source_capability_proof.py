"""Join owner-declared source capabilities to co-located semantic proofs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from common.testing.ac_graph import ProofEdge

_PR_STAGE = "github_ci.merge_authority"
_RELEASE_STAGE = "staging.release_validation"


def _source_classes(proof: ProofEdge) -> tuple[tuple[str, ...], str | None]:
    raw = proof.fields.get("source_classes", ())
    if not isinstance(raw, list | tuple):
        return (), f"proof {proof.proof_id} source_classes must be a list"
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        return (
            (),
            f"proof {proof.proof_id} source_classes must contain non-empty strings",
        )
    return tuple(item.strip() for item in raw), None


def _is_behavioral_stage(proof: ProofEdge, *, stage: str, ci_tier: str) -> bool:
    return (
        proof.scope == "behavioral"
        and proof.stage == stage
        and proof.ci_tier == ci_tier
    )


def validate_source_capability_proofs(
    capabilities: Sequence[Any],
    proofs: Sequence[ProofEdge],
) -> list[str]:
    """Return fail-closed errors for the derived capability-to-proof join."""
    capability_ids = [str(item.capability_id) for item in capabilities]
    duplicates = sorted(
        capability_id
        for capability_id, count in Counter(capability_ids).items()
        if count > 1
    )
    errors: list[str] = []
    if duplicates:
        errors.append(f"duplicate SourceCapability ids: {', '.join(duplicates)}")

    known = set(capability_ids)
    by_source: dict[str, list[ProofEdge]] = {
        capability_id: [] for capability_id in known
    }
    for proof in proofs:
        source_classes, shape_error = _source_classes(proof)
        if shape_error is not None:
            errors.append(shape_error)
            continue
        for source_class in source_classes:
            if source_class not in known:
                errors.append(
                    f"proof {proof.proof_id} claims unknown source capability {source_class}"
                )
                continue
            by_source[source_class].append(proof)

    for capability in capabilities:
        capability_id = str(capability.capability_id)
        status = str(capability.status)
        related = by_source.get(capability_id, [])
        proof_ids = ", ".join(sorted(proof.proof_id for proof in related))

        if status == "gap":
            if related:
                errors.append(
                    f"{capability_id}: gap capability is claimed by proof {proof_ids}"
                )
            continue
        if status not in {"supported", "manual_trusted"}:
            errors.append(f"{capability_id}: unknown SourceCapability status {status}")
            continue

        if not any(
            _is_behavioral_stage(proof, stage=_PR_STAGE, ci_tier="pr_ci")
            for proof in related
        ):
            errors.append(
                f"{capability_id}: {status} capability lacks PR merge-authority proof"
            )
        if status == "supported" and not any(
            _is_behavioral_stage(
                proof,
                stage=_RELEASE_STAGE,
                ci_tier="post_merge_environment",
            )
            for proof in related
        ):
            errors.append(
                f"{capability_id}: supported capability lacks release-validation proof"
            )

    return sorted(set(errors))
