"""Behavioral coverage for the release-coordinate dict `resolve()` emits.

#1435 W1: replaces a brittle `'"short_sha": full_sha[:7]' in resolver` source-text
assertion (formerly folded into test_AC7_10_production_release_promotes_not_rebuilds
in test_post_merge_e2e_gates.py) with a real behavioral test — importing
build_release_coordinate() and asserting its output shape, so a harmless reformat
of release_coordinate.py's resolve() (whitespace, variable names, ordering) can
no longer accidentally pass or fail this check; only the actual short_sha
truncation logic can.
"""

from __future__ import annotations

from common.runtime.release_coordinate import build_release_coordinate


def test_AC7_10_1_short_sha_is_seven_char_prefix_of_full_sha() -> None:
    """AC7.10.1: the release coordinate's short_sha is full_sha's first 7 chars."""
    full_sha = "abcdef0123456789abcdef0123456789abcdef01"

    coordinate = build_release_coordinate("v1.2.3", full_sha)

    assert coordinate["short_sha"] == full_sha[:7]
    assert coordinate["short_sha"] == "abcdef0"
    assert len(coordinate["short_sha"]) == 7


def test_AC7_10_1_release_coordinate_carries_exactly_the_deploy_inputs() -> None:
    """AC7.10.1: the app coordinate excludes infra-owned IaC selection."""
    coordinate = build_release_coordinate(
        "v2.0.0", "1111111111111111111111111111111111111a"
    )

    assert coordinate == {
        "version_ref": "v2.0.0",
        "full_sha": "1111111111111111111111111111111111111a",
        "short_sha": "1111111",
    }
