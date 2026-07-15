"""Pure value objects carried across extraction orchestration boundaries."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import UUID


class PrefectParseParams(TypedDict):
    """JSON-safe wire representation of :class:`ParseJob`."""

    statement_id: str
    filename: str
    institution: str | None
    user_id: str
    account_id: str | None
    file_hash: str
    storage_key: str
    model: str | None
    request_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseJob:
    """Immutable identity and routing context for one statement parse."""

    statement_id: UUID
    filename: str
    institution: str | None
    user_id: UUID
    account_id: UUID | None
    file_hash: str
    storage_key: str
    model: str | None
    request_id: str | None = None

    def to_prefect_params(self) -> PrefectParseParams:
        """Return the explicit JSON-safe contract accepted by the Prefect flow."""
        return {
            "statement_id": str(self.statement_id),
            "filename": self.filename,
            "institution": self.institution,
            "user_id": str(self.user_id),
            "account_id": str(self.account_id) if self.account_id is not None else None,
            "file_hash": self.file_hash,
            "storage_key": self.storage_key,
            "model": self.model,
            "request_id": self.request_id,
        }

    @classmethod
    def from_prefect_params(cls, params: Mapping[str, str | None]) -> ParseJob:
        """Rehydrate a job at the durable-worker boundary."""

        def required(key: str) -> str:
            value = params.get(key)
            if value is None:
                raise ValueError(f"Missing Prefect parse parameter: {key}")
            return value

        account_id = params.get("account_id")
        return cls(
            statement_id=UUID(required("statement_id")),
            filename=required("filename"),
            institution=params.get("institution"),
            user_id=UUID(required("user_id")),
            account_id=UUID(account_id) if account_id else None,
            file_hash=required("file_hash"),
            storage_key=required("storage_key"),
            model=params.get("model"),
            request_id=params.get("request_id"),
        )


@dataclass(frozen=True, slots=True)
class DocumentSource:
    """One normalized address and identity for a document being parsed."""

    path: Path
    content: bytes | None
    url: str | None
    content_hash: str
    filename: str

    @classmethod
    def resolve(
        cls,
        *,
        path: Path,
        content: bytes | None = None,
        url: str | None = None,
        content_hash: str | None = None,
        filename: str | None = None,
    ) -> DocumentSource:
        """Resolve all legacy source aliases exactly once at the call boundary."""
        return cls(
            path=path,
            content=content,
            url=url,
            content_hash=content_hash or hashlib.sha256(content or b"").hexdigest(),
            filename=filename or path.name,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractedTransactionRow:
    """Typed pre-persistence transaction row produced by document extraction."""

    user_id: UUID
    txn_date: date
    amount: Decimal
    direction: str
    description: str
    reference: str | None
    currency: str
    currency_unresolved: bool
    balance_after: Decimal | None
    occurrence_index: int
    dedup_hash: str
