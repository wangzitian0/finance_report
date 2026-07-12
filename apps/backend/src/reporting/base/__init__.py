"""``reporting.base`` — the pure core (mechanism A).

No ORM sessions, no network, no cross-package extension imports: the L1
report-line registry (``l1_registry``) and the static personal report-package
contract/notes/traceability data (``report_package_contract``). The declared
value-object units (``ReportLine``, the three statement responses, the
framework-policy shapes, …) remain typed in ``src/schemas/reporting.py`` —
the contract declares them taxonomy-level without a module path.
"""
