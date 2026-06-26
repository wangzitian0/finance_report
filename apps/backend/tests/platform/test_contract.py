"""The ``platform`` package conforms to its ``PackageContract`` (AC-platform.1.4).

A lighter mirror of the governance gate, scoped to this package: it asserts the
published language (``__all__``) equals ``contract.interface`` and that the
package is discovered + validated cleanly by ``check_package_contract``. The
heavy gate runs in CI over every package; this anchors the AC to an executable
proof in the backend suite.
"""

from common.meta.extension.check_package_contract import (
    REPO_ROOT,
    check_package,
    discover_packages,
)
from common.platform.contract import CONTRACT
from common.testing.ac_proof import ac_proof


@ac_proof(proof_id="test_platform_interface_matches_all", ac_ids=["AC-platform.1.4"], ci_tier="pr_ci")
def test_interface_equals_published_all():
    """AC-platform.1.4: contract.interface equals the BE implementation's __all__."""
    from src.platform import __all__ as published

    assert sorted(CONTRACT.interface) == sorted(published)


@ac_proof(proof_id="test_platform_passes_contract_gate", ac_ids=["AC-platform.1.4"], ci_tier="pr_ci")
def test_platform_package_passes_governance_gate():
    """AC-platform.1.4: check_package_contract validates platform with no violations."""
    packages = discover_packages(REPO_ROOT)
    registered = {p.name: p.contract.klass for p in packages}
    platform = next(p for p in packages if p.name == "platform")

    errors = check_package(platform, registered, REPO_ROOT)

    assert errors == []
