"""Typed contracts for streaming endpoints (chat + report export).

Streaming endpoints (`POST /chat`, `GET /reports/export`,
`GET /reports/package/snapshots/{id}/export`) return a bare
:class:`~fastapi.responses.StreamingResponse`, so FastAPI cannot derive a
``response_model`` for them and the structure of their *out-of-band* payload
(response headers / media type / attachment disposition) was previously
undeclared and untested.

These models declare that structure as an explicit, validated contract
**without changing the wire bytes** clients depend on:

* :class:`ChatStreamEnvelope` describes the chat stream: a ``text/plain`` token
  body plus the typed header sidecar (`X-Session-Id`, optional `X-Model-Name`,
  optional `X-Advisor-Metadata`). ``to_headers()`` reproduces the exact header
  dict (including the cumulative ``Access-Control-Expose-Headers`` list) the
  router emitted before, and ``X-Advisor-Metadata`` is validated against
  :class:`~src.schemas.chat.ChatResponseMetadata` before serialization.
* :class:`ExportStreamEnvelope` describes the report export streams: a typed
  media type plus an ``attachment`` ``Content-Disposition``. ``to_headers()``
  reproduces the exact attachment header.

This module is backend-only and introduces no monetary fields, so the Decimal
rule does not apply here.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.chat import ChatResponseMetadata

# Header names are part of the public wire contract; keep them as constants so
# the router and the contract cannot drift.
SESSION_ID_HEADER = "X-Session-Id"
MODEL_NAME_HEADER = "X-Model-Name"
ADVISOR_METADATA_HEADER = "X-Advisor-Metadata"
EXPOSE_HEADERS_HEADER = "Access-Control-Expose-Headers"
CONTENT_DISPOSITION_HEADER = "Content-Disposition"

# Characters that are unsafe to interpolate into an HTTP header value:
# CR/LF enable header injection / response splitting; the double-quote and
# semicolon break out of the Content-Disposition parameter; path separators
# would leak directory structure into the suggested filename.
_UNSAFE_FILENAME_CHARS = frozenset('\r\n";/\\')


class ChatStreamMediaType(str, Enum):
    """Wire media type for the chat streaming body (plain token text)."""

    TEXT_PLAIN = "text/plain"


class ExportStreamMediaType(str, Enum):
    """Wire media types supported by the report export streams."""

    CSV = "text/csv"
    JSON = "application/json"


class ChatStreamEnvelope(BaseModel):
    """Typed envelope for the ``POST /chat`` streaming response.

    The streamed *body* is a sequence of UTF-8 ``text/plain`` answer tokens; it
    is intentionally schema-less prose. The *metadata* that the previous code
    smuggled through ad-hoc headers is what this envelope makes typed and
    testable:

    * ``session_id`` -> ``X-Session-Id``
    * ``model_name`` -> ``X-Model-Name`` (omitted when ``None``)
    * ``advisor_metadata`` -> ``X-Advisor-Metadata`` (omitted when empty)

    ``to_headers()`` rebuilds the byte-identical header dict the router shipped
    before this contract existed.
    """

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    media_type: ChatStreamMediaType = ChatStreamMediaType.TEXT_PLAIN
    model_name: str | None = Field(
        default=None,
        max_length=120,
        description="Resolved model id exposed via the X-Model-Name response header; omitted when unknown.",
    )
    advisor_metadata: ChatResponseMetadata | None = Field(
        default=None,
        description="Grounding metadata exposed via the X-Advisor-Metadata header; omitted when empty.",
    )

    def _advisor_metadata_header(self) -> str | None:
        """Serialize advisor metadata exactly as the router did, or ``None``.

        Only non-empty metadata (grounded, or any citations/actions) is exposed,
        matching the pre-contract behavior so the wire output is unchanged.
        """
        meta = self.advisor_metadata
        if meta is None:
            return None
        if not (meta.grounded or meta.citations or meta.actions):
            return None
        return meta.model_dump_json()

    def to_headers(self) -> dict[str, str]:
        """Build the exact response header dict for the streaming response."""
        exposed = [SESSION_ID_HEADER]
        headers = {SESSION_ID_HEADER: str(self.session_id)}
        if self.model_name:
            headers[MODEL_NAME_HEADER] = self.model_name
            exposed.append(MODEL_NAME_HEADER)
        metadata_header = self._advisor_metadata_header()
        if metadata_header is not None:
            headers[ADVISOR_METADATA_HEADER] = metadata_header
            exposed.append(ADVISOR_METADATA_HEADER)
        headers[EXPOSE_HEADERS_HEADER] = ", ".join(exposed)
        return headers


class ExportStreamEnvelope(BaseModel):
    """Typed envelope for the report-export streaming responses.

    Export streams carry a fully-rendered document (CSV rows or a JSON blob) as
    an attachment. This envelope declares the media type and filename so the
    ``Content-Disposition`` attachment header is built from a validated source
    instead of an inline f-string.
    """

    model_config = ConfigDict(frozen=True)

    media_type: ExportStreamMediaType
    filename: str = Field(
        min_length=1,
        max_length=255,
        description="Validated attachment filename rendered into the Content-Disposition response header.",
    )

    @field_validator("filename")
    @classmethod
    def _reject_unsafe_filename(cls, value: str) -> str:
        """Reject characters unsafe in an HTTP header value.

        ``filename`` is interpolated directly into the ``Content-Disposition``
        header, so CR/LF (header injection / response splitting), double-quotes,
        semicolons (which would break out of the disposition parameter), and
        path separators must not appear. Length alone is not enough to keep the
        "validated filename" claim honest.
        """
        if _UNSAFE_FILENAME_CHARS.intersection(value):
            raise ValueError(
                "filename must not contain CR, LF, double-quote, semicolon, or path separators",
            )
        return value

    def to_headers(self) -> dict[str, str]:
        """Build the attachment header dict for the export streaming response."""
        return {CONTENT_DISPOSITION_HEADER: f"attachment; filename={self.filename}"}
