"""Common exception utilities for FastAPI routers."""

from typing import NoReturn

from fastapi import HTTPException, status


def raise_not_found(resource_name: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource_name} not found",
    )


def raise_bad_request(detail: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
    )


def raise_internal_error(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    ) from cause
