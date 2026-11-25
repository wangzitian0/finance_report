"""Decoding values of the extraction model calls (#3153).

One place for the values that the old settings ``AI_JSON_*`` held. The SDK owns every other default. A change is a
code change: changing `JSON_MAX_TOKENS`, `EXTRACTION_TIMEOUT_SECONDS`, or `thinking` alters model call behavior and cassettes.
"""

from __future__ import annotations

#: The cap on the answer of a JSON call (statement extraction and transaction classification), in tokens.
JSON_MAX_TOKENS = 32768
#: The longest wait for the next chunk of a streamed extraction answer, in seconds.
EXTRACTION_TIMEOUT_SECONDS = 360.0
