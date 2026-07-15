"""``llm.extension`` — the impure edges: provider SDK, storage, config, cassette.

Adapters over the ``base`` ports: the litellm transport (``client.py``, the
single litellm chokepoint), the model catalogue (``catalog.py``), provider
routing (``routing.py``), the env/DB config sources + layered factory, the
input-keyed cassette record/replay subsystem, and the ORM entities
(``sql.py``, registered on ``Base.metadata`` via ``src.orm_registry``).

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
from src.llm.extension.ocr_client import ocr_layout_call
from src.llm.extension.routing import LitellmCall, build_call
from src.llm.extension.semantic_scoring import ai_semantic_score
from src.llm.extension.streaming import (
    AIStreamError,
    accumulate_stream,
    stream_ai_chat,
    stream_ai_json,
)

__all__ = [
    "AIStreamError",
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
    "accumulate_stream",
    "ai_semantic_score",
    "build_call",
    "fingerprint",
    "get_config_source",
    "get_usage_meter",
    "miss_summary",
    "ocr_layout_call",
    "protocol_for",
    "stream_ai_chat",
    "stream_ai_json",
]
