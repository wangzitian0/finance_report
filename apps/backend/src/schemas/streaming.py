"""Typed contracts for streaming endpoints (chat + report export)."""

from __future__ import annotations

from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.chat import ChatResponseMetadata

SESSION_ID_HEADER = "X-Session-Id"
MODEL_NAME_HEADER = "X-Model-Name"
ADVISOR_METADATA_HEADER = "X-Advisor-Metadata"
EXPOSE_HEADERS_HEADER = "Access-Control-Expose-Headers"
CONTENT_DISPOSITION_HEADER = "Content-Disposition"
_UNSAFE_FILENAME_CHARS = frozenset('\r\n";/\\')


class ChatStreamMediaType(str, Enum):
    TEXT_PLAIN = "text/plain"


class ExportStreamMediaType(str, Enum):
    CSV = "text/csv"
    JSON = "application/json"
    ZIP = "application/zip"


class ChatStreamEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID
    media_type: ChatStreamMediaType = ChatStreamMediaType.TEXT_PLAIN
    model_name: Annotated[str, Field(max_length=120)] | None = None
    advisor_metadata: ChatResponseMetadata | None = None

    def _advisor_metadata_header(self) -> str | None:
        meta = self.advisor_metadata
        if meta is None or not (meta.grounded or meta.citations or meta.actions):
            return None
        return meta.model_dump_json()

    def to_headers(self) -> dict[str, str]:
        exposed = [SESSION_ID_HEADER]
        headers = {SESSION_ID_HEADER: str(self.session_id)}
        if self.model_name:
            headers[MODEL_NAME_HEADER] = self.model_name
            exposed.append(MODEL_NAME_HEADER)
        if (metadata_header := self._advisor_metadata_header()) is not None:
            headers[ADVISOR_METADATA_HEADER] = metadata_header
            exposed.append(ADVISOR_METADATA_HEADER)
        headers[EXPOSE_HEADERS_HEADER] = ", ".join(exposed)
        return headers


class ExportStreamEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    media_type: ExportStreamMediaType
    filename: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("filename")
    @classmethod
    def _reject_unsafe_filename(cls, value: str) -> str:
        if _UNSAFE_FILENAME_CHARS.intersection(value):
            raise ValueError("filename must not contain CR, LF, double-quote, semicolon, or path separators")
        return value

    def to_headers(self) -> dict[str, str]:
        return {CONTENT_DISPOSITION_HEADER: f"attachment; filename={self.filename}"}
