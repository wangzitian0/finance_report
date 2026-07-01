"""`DependencyKind` — how an external dependency must be tested.

The two kinds decide the substitute strategy (see `common/runtime/readme.md`):
`CODE_DOMINANT` is deterministic (a light in-process backend behaves identically
to the real one, so it is behaviourally equivalent in every environment);
`MODEL_DOMINANT` is non-deterministic (output depends on the real service, so CI
replays an input-keyed recording and the real behaviour is proven on staging).
"""

from __future__ import annotations

from enum import Enum


class DependencyKind(str, Enum):
    """The testing character of an external dependency."""

    CODE_DOMINANT = "code_dominant"
    MODEL_DOMINANT = "model_dominant"
