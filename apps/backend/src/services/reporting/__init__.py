"""Former home of the reporting implementation — folded into ``src.reporting``.

The reporting package physically moved to ``apps/backend/src/reporting/``
(#1666, umbrella #1416); import it via ``from src.reporting import …``.

This directory survives only for ``manual_valuation.py``, which is owned by
the in-flight pricing cutover (#1610) and deliberately excluded from the
reporting package (pricing owns valuation observations/staleness). #1610
deletes this directory when it re-homes manual valuation.
"""
