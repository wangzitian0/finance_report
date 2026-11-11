"""Server-side OpenPanel product-analytics emitter (BE->OpenPanel)."""

from __future__ import annotations

import logging
import threading
from typing import Any

import src.config

settings = src.config.settings
logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 5.0


def is_configured() -> bool:
    return bool((settings.openpanel_client_id or "").strip() and (settings.openpanel_api_url or "").strip())


def _track_endpoint() -> str:
    return (settings.openpanel_api_url or "").strip().rstrip("/") + "/track"


def build_payload(event: str, properties: dict[str, Any] | None) -> dict[str, Any]:
    """OpenPanel ``/track`` body omitting ``profileId`` (null is rejected by OpenPanel Zod validation)."""
    env = (settings.openpanel_environment or "").strip() or settings.environment
    return {
        "type": "track",
        "payload": {
            "name": event,
            "properties": {"source": "backend", "deployment_environment": env, **(properties or {})},
        },
    }


def _post(payload: dict[str, Any], client_id: str, endpoint: str) -> None:
    try:
        import httpx

        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            client.post(endpoint, json=payload, headers={"openpanel-client-id": client_id}).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.debug("OpenPanel backend track failed for %r: %s", payload.get("payload", {}).get("name"), exc)


def track(event: str, properties: dict[str, Any] | None = None) -> bool:
    if not is_configured():
        return False
    threading.Thread(
        target=_post,
        args=(build_payload(event, properties), (settings.openpanel_client_id or "").strip(), _track_endpoint()),
        daemon=True,
    ).start()
    return True
