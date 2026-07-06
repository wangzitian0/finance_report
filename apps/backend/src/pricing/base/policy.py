"""``ResolutionPolicy`` — how a consumer wants conflicting observations resolved."""

from __future__ import annotations

from dataclasses import dataclass

from src.pricing.base.observation import Authority


@dataclass(frozen=True, slots=True)
class ResolutionPolicy:
    """How to pick among several observations for the same subject/as_of window.

    ``max_age_days`` bounds how far back ``resolve`` will look for a candidate
    (``None`` = unbounded); ``min_authority`` filters out sources the caller
    doesn't trust for this use (e.g. reporting may exclude bare ``CRAWLER``
    ticks for its year-end snapshot). Per boundary ruling 7 (#1610), staleness
    is a fact ``resolve`` reports — the caller decides via this policy what
    "too old" means for its own tier.
    """

    max_age_days: int | None = None
    min_authority: Authority = Authority.CRAWLER
