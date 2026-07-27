"""``reporting.base`` — the pure core (mechanism A).

No ORM sessions, no network, no cross-package extension imports: the L1
report-line registry (``l1_registry``) and the static personal report-package
contract/notes/traceability data (``report_package_contract``), the
reporting-owned framework/line vocabulary (``types``), and cash-flow proof DTOs
(``cash_flow_types``). Other endpoint-only response DTOs remain in
``src/schemas/reporting.py``.
"""

from src.reporting.base.package_contribution import PackageSectionContribution
from src.reporting.base.types import PersonalReportingFrameworkId, PolicyDimension, ReportLineId

__all__ = [
    "PackageSectionContribution",
    "PersonalReportingFrameworkId",
    "PolicyDimension",
    "ReportLineId",
]
