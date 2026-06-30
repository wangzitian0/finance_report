"""``common.ratio`` — the project's ratio/percent narrow waist (#1167 family).

The second base-element value type after ``money`` (see
``common/audit/readme.md#base-packages``): a dimensionless :class:`Ratio` with ONE percent
display policy (2 dp, ROUND_HALF_UP), so performance ratios / allocation shares /
confidence proportions stop diverging across the codebase and across FE/BE.

Dependency-light (stdlib + Decimal). Contract: ``common/ratio/contract/ratio.contract.md``.
"""

from __future__ import annotations

from common.ratio.errors import (
    FloatNotAllowedError,
    InvalidRatioPayloadError,
    RatioError,
    UndefinedRatioError,
)
from common.ratio.ratio import PERCENT_DP, PERCENT_ROUNDING, Ratio
from common.ratio.wire import (
    ratio_from_db_value,
    ratio_from_wire,
    ratio_to_db_value,
    ratio_to_wire,
)

__all__ = [
    "PERCENT_DP",
    "PERCENT_ROUNDING",
    "FloatNotAllowedError",
    "InvalidRatioPayloadError",
    "Ratio",
    "RatioError",
    "UndefinedRatioError",
    "ratio_from_db_value",
    "ratio_from_wire",
    "ratio_to_db_value",
    "ratio_to_wire",
]
