"""LLM record/replay cassette layer (EPIC-023 AC23.5)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.llm.base import LLMError, Message
from src.observability import get_logger

logger = get_logger(__name__)


def _find_cassette_dir() -> Path:
    """Locate ``common/testing/fixtures/llm_cassettes`` or fall back to an image-local sentinel."""
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "common" / "testing" / "fixtures" / "llm_cassettes"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "_no_cassettes_in_this_image"


CASSETTE_DIR = _find_cassette_dir()

_VOLATILE_KEYS = frozenset(
    {
        "timestamp",
        "created",
        "created_at",
        "request_id",
        "id",
        "trace_id",
        "x_request_id",
        "nonce",
    }
)
_IMAGE_BYTES_TAG = "image_bytes_sha256"


class CassetteMode(StrEnum):
    """Record/replay modes."""

    REPLAY = "replay"
    RECORD = "record"
    OFF = "off"


class CassetteTag(StrEnum):
    """Evidence claim level of a recorded cassette."""

    CORRECTNESS = "correctness"
    FLOW_ONLY = "flow-only"


class CassetteMiss(LLMError):
    """Raised in ``replay`` mode when no committed cassette matches the request."""

    def __init__(self, key: str, *, scene: str | None = None) -> None:
        self.key = key
        self.scene = scene
        super().__init__(
            f"LLM cassette MISS in replay mode (key={key}"
            + (f", scene={scene}" if scene else "")
            + "); no network fallback. Re-record with: make llm-record"
        )


class CassetteValidationError(LLMError):
    """Raised when a ``correctness`` cassette fails ground-truth validation at record time."""


ENGAGE_ENV = "LLM_CASSETTE_ENGAGE"
LIVE_ENV = "LLM_LIVE"
REFRESH_ENV = "LLM_CASSETTE_REFRESH"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def layer_engaged() -> bool:
    return _env_flag(ENGAGE_ENV)


def live_forced() -> bool:
    return _env_flag(LIVE_ENV)


def refresh_requested() -> bool:
    return _env_flag(REFRESH_ENV) and not in_ci()


def in_ci() -> bool:
    return _env_flag("CI")


def _hash_image_bytes(data: bytes | bytearray | memoryview) -> str:
    return f"{_IMAGE_BYTES_TAG}:{hashlib.sha256(bytes(data)).hexdigest()}"


def _normalize(value: Any) -> Any:
    """Strip volatile metadata fields and hash raw image bytes deterministically."""
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in value.items() if str(k).lower() not in _VOLATILE_KEYS}
    if isinstance(value, bytes | bytearray | memoryview):
        return _hash_image_bytes(value)
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return [_normalize(v) for v in value]
    return value


def _canonical_request(
    *,
    role: str,
    messages: Sequence[Message],
    decode_params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the model-id-agnostic semantic request payload."""
    return {
        "role": str(role),
        "messages": _normalize(list(messages)),
        "decode_params": _normalize(dict(decode_params or {})),
    }


def fingerprint(
    *,
    role: str,
    messages: Sequence[Message],
    decode_params: Mapping[str, Any] | None = None,
) -> str:
    """Compute SHA-256 of the canonical semantic request."""
    canonical = _canonical_request(role=role, messages=messages, decode_params=decode_params)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Cassette:
    """One committed record/replay entry: semantic request plus frozen response."""

    key: str
    role: str
    tag: CassetteTag
    request: dict[str, Any]
    response: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "fingerprint": self.key,
            "role": self.role,
            "tag": self.tag.value,
            "request": self.request,
            "response": self.response,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Cassette:
        return cls(
            key=str(data["fingerprint"]),
            role=str(data["role"]),
            tag=CassetteTag(str(data["tag"])),
            request=dict(data["request"]),
            response=dict(data["response"]),
        )


_SESSION_SERVED: set[str] = set()


def session_served_keys() -> frozenset[str]:
    return frozenset(_SESSION_SERVED)


class CassetteStore:
    """Filesystem persistence of committed cassette JSON files keyed by fingerprint."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or CASSETTE_DIR
        self._served: set[str] = set()

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def get(self, key: str) -> Cassette | None:
        path = self._path(key)
        if not path.exists():
            return None
        return Cassette.from_json(json.loads(path.read_text(encoding="utf-8")))

    def mark_served(self, key: str) -> None:
        self._served.add(key)
        _SESSION_SERVED.add(key)

    def served_keys(self) -> frozenset[str]:
        return frozenset(self._served)

    def put(self, cassette: Cassette) -> bool:
        """Persist ``cassette`` idempotently; return True only when disk bytes changed."""
        self._dir.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(cassette.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = self._path(cassette.key)
        if path.exists() and path.read_text(encoding="utf-8") == blob:
            return False
        path.write_text(blob, encoding="utf-8")
        return True


CorrectnessValidator = Callable[[dict[str, Any]], bool]


def require_correctness_validator(tag: CassetteTag, validator: Any, *, role: str) -> None:
    if tag is CassetteTag.CORRECTNESS and validator is None:
        raise CassetteValidationError(
            f"correctness cassette (role={role}) requires a ground-truth validator to record"
        )


def persist_recorded_cassette(
    store: CassetteStore,
    *,
    key: str,
    role: str,
    tag: CassetteTag,
    validator: Any,
    messages: Sequence[Message],
    decode_params: Mapping[str, Any] | None,
    response: dict[str, Any],
    failure_noun: str = "response",
) -> bool:
    """Validate (when tagged correctness), normalize volatile fields, and write cassette to store."""
    if tag is CassetteTag.CORRECTNESS:
        try:
            ok = bool(validator(response)) if validator is not None else False
        except Exception as exc:  # noqa: BLE001 - any validator error refuses the record
            raise CassetteValidationError(
                f"correctness validation raised for role={role}: {type(exc).__name__}"
            ) from exc
        if not ok:
            raise CassetteValidationError(
                f"correctness cassette (role={role}, key={key}) refused: {failure_noun} failed "
                "ground-truth validation; recording it would freeze a wrong answer"
            )
    request = _canonical_request(role=role, messages=messages, decode_params=decode_params)
    return store.put(Cassette(key=key, role=role, tag=tag, request=request, response=_normalize(response)))


class CassetteRecorder:
    """Wrap an async chat-completion callable with record/replay policy."""

    def __init__(self, store: CassetteStore | None = None, *, mode: CassetteMode | None = None) -> None:
        self._store = store or CassetteStore()
        self._mode = mode
        self._misses: list[str] = []

    @property
    def mode(self) -> CassetteMode:
        return self._mode if self._mode is not None else CassetteMode.OFF

    @property
    def misses(self) -> list[str]:
        return list(self._misses)

    async def call(
        self,
        live_call: Any,
        *,
        role: str,
        messages: Sequence[Message],
        decode_params: Mapping[str, Any] | None = None,
        tag: CassetteTag = CassetteTag.FLOW_ONLY,
        validator: CorrectnessValidator | None = None,
    ) -> dict[str, Any]:
        mode = self.mode
        key = fingerprint(role=role, messages=messages, decode_params=decode_params)
        if mode is CassetteMode.OFF:
            return await live_call()
        if mode is CassetteMode.REPLAY:
            cassette = self._store.get(key)
            if cassette is None:
                self._misses.append(key)
                raise CassetteMiss(key, scene=role)
            self._store.mark_served(key)
            return cassette.response

        require_correctness_validator(tag, validator, role=role)
        response = await live_call()
        changed = persist_recorded_cassette(
            self._store,
            key=key,
            role=role,
            tag=tag,
            validator=validator,
            messages=messages,
            decode_params=decode_params,
            response=response,
        )
        logger.info("llm cassette recorded", key=key, role=role, tag=tag.value, changed=changed)
        return response


def miss_summary(keys: Sequence[str]) -> str:
    """Format an actionable batch summary for replay misses."""
    if not keys:
        return ""
    unique = sorted(set(keys))
    return (
        f"{len(unique)} cassette(s) need re-record: {', '.join(unique)}; "
        "run make llm-record (no committed cassette matched the request in replay mode)."
    )
