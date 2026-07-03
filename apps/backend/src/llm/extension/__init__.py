"""``llm.extension`` — the impure edges: provider SDK, storage, config, cassette.

Adapters over the ``base`` ports: the litellm transport (``client.py``, the
single litellm chokepoint), the model catalogue (``catalog.py``), provider
routing (``routing.py``), the env/DB config sources + layered factory, the
input-keyed cassette record/replay subsystem, and the ORM entities
(``sql.py``, registered on ``Base.metadata`` via ``src.models._registry``).

This ``__init__`` deliberately does NOT import ``client``/``catalog`` — they
require ``litellm``, which minimal tooling environments don't install. The
package root exposes their symbols lazily (PEP 562); everything re-exported
here is litellm-free.
"""

from __future__ import annotations

from src.llm.extension.cassette import (
    CASSETTE_DIR,
    Cassette,
    CassetteMiss,
    CassetteMode,
    CassetteRecorder,
    CassetteStore,
    CassetteTag,
    CassetteValidationError,
    current_mode,
    fingerprint,
    miss_summary,
)
from src.llm.extension.db_config import DbConfigSource
from src.llm.extension.env_config import EnvConfigSource, protocol_for
from src.llm.extension.factory import (
    LayeredConfigSource,
    get_config_source,
    get_usage_meter,
)
from src.llm.extension.routing import LitellmCall, build_call

__all__ = [
    "CASSETTE_DIR",
    "Cassette",
    "CassetteMiss",
    "CassetteMode",
    "CassetteRecorder",
    "CassetteStore",
    "CassetteTag",
    "CassetteValidationError",
    "DbConfigSource",
    "EnvConfigSource",
    "LayeredConfigSource",
    "LitellmCall",
    "build_call",
    "current_mode",
    "fingerprint",
    "get_config_source",
    "get_usage_meter",
    "miss_summary",
    "protocol_for",
]
