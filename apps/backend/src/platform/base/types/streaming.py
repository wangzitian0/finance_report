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
  :class:`~src.advisor.base.types.chat.ChatResponseMetadata` before serialization.
* :class:`ExportStreamEnvelope` describes the report export streams: a typed
  media type plus an ``attachment`` ``Content-Disposition``. ``to_headers()``
  reproduces the exact attachment header.

This module is backend-only and introduces no monetary fields, so the Decimal
rule does not apply here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Header names are part of the public wire contract; keep them as constants so
# the router and the contract cannot drift.
CONTENT_DISPOSITION_HEADER = "Content-Disposition"

# Characters that are unsafe to interpolate into an HTTP header value:
# CR/LF enable header injection / response splitting; the double-quote and
# semicolon break out of the Content-Disposition parameter; path separators
# would leak directory structure into the suggested filename.
_UNSAFE_FILENAME_CHARS = frozenset('\r\n";/\\')


class ExportStreamMediaType(StrEnum):
    """Wire media types supported by the report export streams."""

    CSV = "text/csv"
    JSON = "application/json"


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
