"""Thin re-export shim for the ``manual_valuation.py`` survivor (#1666/#1610).

The reporting core moved to ``src.reporting`` (#1666). This shim exists only
so the byte-untouched ``manual_valuation.py`` next door — owned by the
in-flight pricing cutover (#1610) — keeps resolving its one import
(``from src.services.reporting._core import _valuation_line_name``). #1610
deletes it together with the rest of this directory.
"""

from src.reporting import _valuation_line_name

__all__ = ["_valuation_line_name"]
