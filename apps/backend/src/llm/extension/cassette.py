"""LLM record and replay cassette persistence and validation."""

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
    """Locate ``common/testing/fixtures/llm_cassettes`` or return an image sentinel."""
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
    """Record and replay execution modes."""

    REPLAY = "replay"
    RECORD = "record"
    OFF = "off"


class CassetteTag(StrEnum):
    """Claim scope for a recorded cassette response."""

    CORRECTNESS = "correctness"
    FLOW_ONLY = "flow-only"


class CassetteMiss(LLMError):
    """Raise when replay mode finds no committed cassette for a request."""

    def __init__(self, key: str, *, scene: str | None = None) -> None:
        self.key = key
        self.scene = scene
        super().__init__(
            f"LLM cassette MISS in replay mode (key={key}"
            + (f", scene={scene}" if scene else "")
            + "); no network fallback. Re-record with: make llm-record"
        )


class CassetteValidationError(LLMError):
    """Raise when a correctness cassette fails ground-truth validation."""


ENGAGE_ENV = "LLM_CASSETTE_ENGAGE"
LIVE_ENV = "LLM_LIVE"
REFRESH_ENV = "LLM_CASSETTE_REFRESH"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def layer_engaged() -> bool:
    """Return True when the test harness activates the cassette layer."""
    return _env_flag(ENGAGE_ENV)


def live_forced() -> bool:
    """Return True when the environment forces live provider calls."""
    return _env_flag(LIVE_ENV)


def refresh_requested() -> bool:
    """Return True when local cassette re-recording is requested outside CI."""
    return _env_flag(REFRESH_ENV) and not in_ci()


def in_ci() -> bool:
    return _env_flag("CI")


def _hash_image_bytes(data: bytes | bytearray | memoryview) -> str:
    return f"{_IMAGE_BYTES_TAG}:{hashlib.sha256(bytes(data)).hexdigest()}"


def _normalize(value: Any) -> Any:
    """Strip volatile fields and replace raw image bytes with SHA-256 digests."""
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
    """Build the model-agnostic semantic request payload."""
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
    """Compute the SHA-256 digest of the canonical semantic request."""
    canonical = _canonical_request(role=role, messages=messages, decode_params=decode_params)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Cassette:
    """Committed record and replay entry holding semantic request and response."""

    key: str
    role: str
    tag: CassetteTag
    request: dict[str, Any]
    response: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        # Name the digest field ``fingerprint`` to avoid generic-api-key false positives.
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
    """Filesystem store for committed cassette JSON files keyed by fingerprint."""

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
        """Write ``cassette`` to disk when its canonical JSON bytes change."""
        self._dir.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(cassette.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = self._path(cassette.key)
        if path.exists() and path.read_text(encoding="utf-8") == blob:
            return False
        path.write_text(blob, encoding="utf-8")
        return True


CorrectnessValidator = Callable[[dict[str, Any]], bool]


def require_correctness_validator(
    tag: CassetteTag,
    validator: CorrectnessValidator | None,
    *,
    role: str,
) -> None:
    """Require a ground-truth validator before recording a correctness cassette."""
    if tag is CassetteTag.CORRECTNESS and validator is None:
        raise CassetteValidationError(f"correctness cassette (role={role}) requires a ground-truth validator to record")


def persist_validated_cassette(
    store: CassetteStore,
    *,
    key: str,
    role: str,
    tag: CassetteTag,
    validator: CorrectnessValidator | None,
    messages: Sequence[Message],
    decode_params: Mapping[str, Any] | None,
    response: dict[str, Any],
    normalize_response: bool = False,
) -> bool:
    """Validate correctness responses against ground truth and write the cassette."""
    if tag is CassetteTag.CORRECTNESS:
        try:
            ok = bool(validator(response)) if validator is not None else False
        except Exception as exc:  # noqa: BLE001
            raise CassetteValidationError(
                f"correctness validation raised for role={role}: {type(exc).__name__}"
            ) from exc
        if not ok:
            raise CassetteValidationError(
                f"correctness cassette (role={role}, key={key}) refused: response failed "
                "ground-truth validation; recording it would freeze a wrong answer"
            )
    stored_response = _normalize(response) if normalize_response else response
    request = _canonical_request(role=role, messages=messages, decode_params=decode_params)
    return store.put(Cassette(key=key, role=role, tag=tag, request=request, response=stored_response))


class CassetteRecorder:
    """Record or replay non-streaming chat-completion payloads."""

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
        """Return a completion response via live call, replay, or validated record."""
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
        changed = persist_validated_cassette(
            self._store,
            key=key,
            role=role,
            tag=tag,
            validator=validator,
            messages=messages,
            decode_params=decode_params,
            response=response,
            normalize_response=True,
        )
        logger.info("llm cassette recorded", key=key, role=role, tag=tag.value, changed=changed)
        return response


def miss_summary(keys: Sequence[str]) -> str:
    """Format one batch summary for replay misses."""
    if not keys:
        return ""
    unique = sorted(set(keys))
    listed = ", ".join(unique)
    return (
        f"{len(unique)} cassette(s) need re-record: {listed}; "
        "run make llm-record (no committed cassette matched the request in replay mode)."
    )
