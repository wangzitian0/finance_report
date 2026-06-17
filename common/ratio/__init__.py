"""``common.ratio`` — the project's ratio/percent narrow waist (#1167 family).

The second base-element value type after ``money`` (see
``docs/ssot/base-packages.md``): a dimensionless :class:`Ratio` with ONE percent
display policy (2 dp, ROUND_HALF_UP), so performance ratios / allocation shares /
confidence proportions stop diverging across the codebase and across FE/BE.

Dependency-light (stdlib + Decimal). Contract: ``common/ratio/contract/ratio.contract.md``.
"""

from __future__ import annotations

from common.ratio.errors import FloatNotAllowedError, RatioError, UndefinedRatioError
from common.ratio.ratio import PERCENT_DP, PERCENT_ROUNDING, Ratio

__all__ = [
    "PERCENT_DP",
    "PERCENT_ROUNDING",
    "FloatNotAllowedError",
    "Ratio",
    "RatioError",
    "UndefinedRatioError",
]
