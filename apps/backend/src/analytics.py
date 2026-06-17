"""Server-side OpenPanel product-analytics emitter (BE->OpenPanel).

The backend half of the OpenPanel integration, symmetric with the frontend's
official ``@openpanel/nextjs`` SDK: this uses the official ``openpanel`` Python
package (not a hand-rolled HTTP client) so both sides speak OpenPanel through its
base SDK.

Why a backend emitter at all (the frontend already tracks)? Server-side events
are *authoritative* — they fire from the backend regardless of the browser
(adblock / no-JS / closed tab), so a conversion the server actually completed
(e.g. a report package persisted) is never under-counted. This complements, not
replaces, the FE analytics.

Config-gated: when ``OPENPANEL_CLIENT_ID`` is unset (local / CI / preview without
a project) every call is a complete no-op — same posture as the FE SDK and the
OTel exporter. Failures are swallowed so analytics can never break a request.

Our OpenPanel clients are configured ``ignoreCorsAndSecret=true``, so no
``client_secret`` is required (the SDK accepts ``client_id`` + ``api_url`` alone).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)

# The OpenPanel SDK runs its own background daemon thread + send queue, so we keep
# ONE module-level client (never one-per-event). Lazily built on first use.
_client: Any = None
_client_lock = threading.Lock()


def is_configured() -> bool:
    """True when a per-env OpenPanel project is wired (client-id + api url)."""
    return bool((settings.openpanel_client_id or "").strip() and (settings.openpanel_api_url or "").strip())


def _get_client() -> Any:
    """Return the shared OpenPanel client, or None when analytics is unconfigured.

    Built once (double-checked lock) because constructing it spins a daemon thread.
    ``set_global_properties`` stamps every event with source=backend + the
    deployment environment, mirroring the FE event contract.
    """
    global _client
    if not is_configured():
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                from openpanel import OpenPanel

                client = OpenPanel(
                    client_id=settings.openpanel_client_id.strip(),
                    api_url=settings.openpanel_api_url.strip(),
                )
                env = (settings.openpanel_environment or "").strip() or settings.environment
                try:
                    client.set_global_properties({"source": "backend", "deployment_environment": env})
                except Exception as exc:  # noqa: BLE001 — never let analytics setup break a request
                    logger.debug("OpenPanel set_global_properties failed: %s", exc)
                _client = client
    return _client


def track(event: str, properties: dict[str, Any] | None = None) -> bool:
    """Emit one OpenPanel event from the backend via the official SDK.

    Returns True if the event was handed to the SDK (which sends it on its own
    background thread), False when unconfigured. Config-gated and NEVER raises —
    any error is logged at debug and swallowed so a telemetry hiccup cannot fail
    the caller's request. Pair with FastAPI ``BackgroundTasks`` to keep even the
    one-time lazy client init off the response path.
    """
    client = _get_client()
    if client is None:
        return False
    try:
        client.track(event, properties or {})
        return True
    except Exception as exc:  # noqa: BLE001 — analytics must never break a request
        logger.debug("OpenPanel backend track failed for %r: %s", event, exc)
        return False
