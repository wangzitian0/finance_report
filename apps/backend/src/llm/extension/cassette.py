"""LLM record/replay cassette layer (EPIC-023 AC23.5).

Make LLM calls deterministic in CI via a record/replay (cassette) layer. A
cassette is a committed JSON file holding the *semantic* request fingerprint and
the frozen provider response. Three modes, selected by ``LLM_CASSETTE_MODE``:

- ``replay`` (CI default): serve the recorded response with **zero network and no
  API key**. A cache MISS is a HARD FAILURE — it raises with an actionable batch
  summary ("N cassettes need re-record: <keys>; run make llm-record"); it never
  falls back to the network.
- ``record`` (local, with a provider key): perform the real provider call and
  write/update the cassette. Re-recording an unchanged request is idempotent.
- ``off`` (local dev default): normal live call, no cassette involvement.

Scope (anti-false-confidence): record/replay is regression protection for KNOWN
inputs only. It does NOT discover new real-world document shapes (that stays the
staging real-doc audit loop), and **CI green != a real unknown statement works**.
Provider-specific correctness is the staging ``-m llm`` gate's job, not the
cassette tests'. See ``common/llm/readme.md#cassettes``.

The fingerprint is computed on the *semantic request and modality role* —
``sha256(normalize(role + messages + decode params + image-bytes hash))`` — and
deliberately **NOT the exact model id**, so bumping ``glm-5.1 -> 5.2`` does not
invalidate every cassette: refreshing content is a re-record, the key is stable.
Volatile fields (timestamps, random request ids) are stripped before hashing.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.llm.base import LLMConfigError, LLMError, Message
from src.observability import get_logger

logger = get_logger(__name__)


def _find_cassette_dir() -> Path:
    """Locate ``common/testing/fixtures/llm_cassettes`` from the repo root.

    Cassettes live under the `testing` package's fixture home so they are
    reviewed in the diff (the frozen response is visible) — deliberately
    **outside** ``apps/backend``, so the Docker build (``COPY src ./src`` only,
    no ``common/``) never ships them. That means this module also loads inside
    the built image, where there is no monorepo root above ``/app`` to find:
    walk upward bounded by the filesystem root (never past it, unlike a fixed
    ``parents[N]``) and fall back to a sentinel that simply has no cassettes.
    ``off`` mode (the image's runtime default) never reads this path; only the
    full-checkout CI/local ``replay``/``record`` paths do.
    """
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "common" / "testing" / "fixtures" / "llm_cassettes"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "_no_cassettes_in_this_image"


# Where committed cassettes live: the `testing` package's fixture home, so they
# are reviewed in the diff (the frozen response is visible) and never shipped in
# the app image.
CASSETTE_DIR = _find_cassette_dir()

# Env var selecting the mode; CI defaults to replay, local dev to off.
CASSETTE_MODE_ENV = "LLM_CASSETTE_MODE"

# Fields that never affect the response semantically — stripped before hashing so
# a re-record with a new timestamp / request id does not change the key. This is
# the ONLY normalisation applied to message/param content; anything else that can
# change the bytes the provider sees MUST change the fingerprint (see tests).
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

# A short prefix for image-bytes references so the hashing is deterministic and
# the cassette key stays stable regardless of where the bytes came from.
_IMAGE_BYTES_TAG = "image_bytes_sha256"


class CassetteMode(StrEnum):
    """The three record/replay modes."""

    REPLAY = "replay"
    RECORD = "record"
    OFF = "off"


class CassetteTag(StrEnum):
    """What a cassette's frozen response is allowed to claim.

    - ``CORRECTNESS``: the response was validated against fixture ground-truth at
      record time (a ``correctness`` cassette MUST refuse to record if validation
      fails). A passing replay therefore asserts the LLM read the inputs right.
    - ``FLOW_ONLY``: asserts response *handling* only — it never claims the LLM
      read numbers correctly. Used for wiring/plumbing tests.
    """

    CORRECTNESS = "correctness"
    FLOW_ONLY = "flow-only"


class CassetteMiss(LLMError):
    """Raised in ``replay`` mode when no cassette matches the request.

    Carries the missing key so the runner can batch-summarise every miss in a
    single actionable message instead of N cryptic errors. Never retryable — the
    fix is to re-record, not to retry.
    """

    def __init__(self, key: str, *, scene: str | None = None) -> None:
        self.key = key
        self.scene = scene
        super().__init__(
            f"LLM cassette MISS in replay mode (key={key}"
            + (f", scene={scene}" if scene else "")
            + "); no network fallback. Re-record with: make llm-record"
        )


class CassetteValidationError(LLMError):
    """A ``correctness`` cassette failed ground-truth validation at record time.

    Refusing to record (rather than silently freezing a wrong response) is the
    whole point of the ``correctness`` tag: a frozen-wrong response would make CI
    green while asserting the LLM read numbers it never read.
    """


# --- Transparent per-request decision knobs (#1596) -------------------------
# All layer-owned. Downstream code and tests never read these: the test harness
# engages the layer once (conftest), deployments/workflows may force LIVE, and
# operators refresh via `make llm-record`. Priority: LIVE > engaged > live.

ENGAGE_ENV = "LLM_CASSETTE_ENGAGE"
LIVE_ENV = "LLM_LIVE"
REFRESH_ENV = "LLM_CASSETTE_REFRESH"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def layer_engaged() -> bool:
    """The cassette layer is active (bootstrapped once by the test harness)."""
    return _env_flag(ENGAGE_ENV)


def live_forced() -> bool:
    """Explicit deployment/workflow config: always the real provider (staging
    ``-m llm`` gates, prod). Deliberate config — allowed even in CI."""
    return _env_flag(LIVE_ENV)


def refresh_requested() -> bool:
    """Operator re-record of existing cassettes (`make llm-record`). Never in CI:
    cassettes are only ever written locally and reviewed in the diff."""
    return _env_flag(REFRESH_ENV) and not in_ci()


def in_ci() -> bool:
    return _env_flag("CI")


def legacy_mode_env_set() -> bool:
    """A process-level LLM_CASSETTE_MODE is the pre-#1596 contract; honored for
    compatibility until the downstream forks are deleted (#1597)."""
    return bool(os.environ.get(CASSETTE_MODE_ENV, "").strip())


def current_mode() -> CassetteMode:
    """The active cassette mode from ``LLM_CASSETTE_MODE`` (default ``off``).

    Unknown values fail closed with a config error rather than silently behaving
    like ``off`` (which would let a CI misconfiguration call the network)."""
    raw = os.environ.get(CASSETTE_MODE_ENV, CassetteMode.OFF.value).strip().lower()
    try:
        return CassetteMode(raw)
    except ValueError as exc:
        raise LLMConfigError(
            f"Invalid {CASSETTE_MODE_ENV}={raw!r}; expected one of {', '.join(m.value for m in CassetteMode)}"
        ) from exc


def _hash_image_bytes(data: bytes | bytearray | memoryview) -> str:
    return f"{_IMAGE_BYTES_TAG}:{hashlib.sha256(bytes(data)).hexdigest()}"


def _normalize(value: Any) -> Any:
    """Recursively strip volatile fields and reduce image bytes to a stable hash.

    The result is a canonical, JSON-serialisable structure used both as the
    fingerprint input and as the stored ``request`` block. Only provably
    output-irrelevant fields are removed (``_VOLATILE_KEYS``); everything else —
    every byte the provider would see — is preserved so a meaningful change
    produces a different key.
    """
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in _VOLATILE_KEYS:
                continue
            out[key] = _normalize(v)
        return out
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _hash_image_bytes(value)
    # str is a Sequence; handle it before the generic sequence branch.
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
    """The semantic request payload — model id deliberately excluded.

    ``role`` is the modality role (e.g. the :class:`~src.llm.base.types.Scene`
    value or ``"text"``/``"vision"``), NOT the model id, so swapping models keeps
    the key stable while a different call site / modality produces a different key.
    """
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
    """``sha256`` of the canonical semantic request (model-id-agnostic).

    Image content given as raw bytes is reduced to a content hash so two requests
    with the same image bytes share a key regardless of transport encoding.
    """
    canonical = _canonical_request(role=role, messages=messages, decode_params=decode_params)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Cassette:
    """One committed record/replay entry: the semantic request plus its response."""

    key: str
    role: str
    tag: CassetteTag
    request: dict[str, Any]
    response: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        # The fingerprint field is named ``fingerprint`` (not ``key``) on purpose:
        # a 64-char hex value next to a JSON field literally named ``key`` trips
        # the secret-scanner's generic-api-key rule (the value looks like an API
        # key). It is a content hash, not a credential.
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


class CassetteStore:
    """Read/write committed cassette JSON files keyed by fingerprint.

    One file per key (``<key>.json``) so a re-record only re-touches the affected
    cassette and the diff stays reviewable. The store does no network I/O — it is
    pure filesystem persistence of frozen responses.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or CASSETTE_DIR
        # Which cassettes this store served (fingerprints) — the substrate for
        # orphan detection (#1596): a committed cassette no full suite ever
        # serves is a leftover from a changed prompt.
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

    def served_keys(self) -> frozenset[str]:
        return frozenset(self._served)

    def put(self, cassette: Cassette) -> bool:
        """Persist ``cassette``; return ``True`` if the bytes changed on disk.

        Idempotent: re-recording an unchanged request writes identical canonical
        JSON, so the file content (and the diff) is unchanged and ``False`` is
        returned. Volatile fields were already stripped by the fingerprint path,
        so a re-record never churns the file just because of a new timestamp.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(cassette.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = self._path(cassette.key)
        if path.exists() and path.read_text(encoding="utf-8") == blob:
            return False
        path.write_text(blob, encoding="utf-8")
        return True


# A correctness validator takes the recorded response dict and returns True when
# it matches the fixture ground-truth. Returning False (or raising) refuses the
# record. ``flow-only`` cassettes pass ``None``.
CorrectnessValidator = Callable[[dict[str, Any]], bool]


class CassetteRecorder:
    """Wraps a chat-completion callable with record/replay behaviour.

    ``live_call`` is the real (async) provider call: ``await live_call() -> dict``
    returning the response payload to freeze. It is invoked ONLY in ``record`` and
    ``off`` modes — never in ``replay`` (so replay needs no API key and makes no
    network call). The recorder is provider-agnostic: any provider's response dict
    can be frozen, so re-recording works with any provider key, not only GLM.
    """

    def __init__(self, store: CassetteStore | None = None, *, mode: CassetteMode | None = None) -> None:
        self._store = store or CassetteStore()
        self._mode = mode
        # Misses collected during a replay run, so the runner can batch-summarise.
        self._misses: list[str] = []

    @property
    def mode(self) -> CassetteMode:
        return self._mode if self._mode is not None else current_mode()

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
        """Return a response for the request, recording or replaying per mode."""
        mode = self.mode
        key = fingerprint(role=role, messages=messages, decode_params=decode_params)

        if mode is CassetteMode.OFF:
            return await live_call()

        if mode is CassetteMode.REPLAY:
            cassette = self._store.get(key)
            if cassette is None:
                self._misses.append(key)
                raise CassetteMiss(key, scene=role)
            return cassette.response

        # record: real provider call + persist (validated for correctness tags).
        if tag is CassetteTag.CORRECTNESS and validator is None:
            raise CassetteValidationError(
                f"correctness cassette (role={role}) requires a ground-truth validator to record"
            )
        response = await live_call()
        if tag is CassetteTag.CORRECTNESS:
            # Validate the RAW provider response (what it actually returned).
            ok = False
            try:
                ok = bool(validator(response)) if validator is not None else False
            except Exception as exc:  # noqa: BLE001 - any validator error refuses the record
                raise CassetteValidationError(
                    f"correctness validation raised for role={role}: {type(exc).__name__}"
                ) from exc
            if not ok:
                raise CassetteValidationError(
                    f"correctness cassette (role={role}, key={key}) refused: response failed "
                    "ground-truth validation; recording it would freeze a wrong answer"
                )
        # Strip volatile fields (timestamps, random ids) from the STORED response
        # too, so re-recording an unchanged semantic response rewrites identical
        # bytes — a provider's per-call ``id``/``created``/``request_id`` must not
        # churn the committed cassette.
        stored_response = _normalize(response)
        request = _canonical_request(role=role, messages=messages, decode_params=decode_params)
        cassette = Cassette(key=key, role=role, tag=tag, request=request, response=stored_response)
        changed = self._store.put(cassette)
        logger.info("llm cassette recorded", key=key, role=role, tag=tag.value, changed=changed)
        return response


def miss_summary(keys: Sequence[str]) -> str:
    """The actionable batch summary for replay misses (one message, not N errors)."""
    if not keys:
        return ""
    unique = sorted(set(keys))
    listed = ", ".join(unique)
    return (
        f"{len(unique)} cassette(s) need re-record: {listed}; "
        "run make llm-record (no committed cassette matched the request in replay mode)."
    )
