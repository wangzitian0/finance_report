"""``reporting.extension`` — the impure edges.

Statement generation over the ledger (balance sheet / income statement /
cash flow / net worth / lineage), framework-aware report assembly, package
readiness/traceability/export, snapshot persistence, the confidence metric,
and the injected FX seam (``fx_gateway``). Everything here may touch the DB
and other packages' published interfaces; the pure core lives in ``base/``.
"""
