"""The two SHA-256 digest definitions of the backend (#2768).

A digest is stored data: trace records, command digests and result ids keep these
values. Both functions keep the exact bytes of the private copies that they replaced.
Do not change the separators, the sort order, the ``default`` rule or the encoding.

* ``canonical_json_digest`` hashes the canonical JSON text of one value.
* ``text_digest`` hashes one string as it is.

``canonical_json_digest("x")`` is not ``text_digest("x")``: the canonical text of a
string has quotes. ``text_digest(json.dumps(value, sort_keys=True, separators=(",", ":")))``
equals ``canonical_json_digest(value)`` when no value needs the ``default=str`` rule.
"""

from __future__ import annotations

import hashlib
import json


def canonical_json_digest(value: object) -> str:
    """Return the SHA-256 hex digest of the canonical JSON text of ``value``."""
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def text_digest(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode()).hexdigest()
