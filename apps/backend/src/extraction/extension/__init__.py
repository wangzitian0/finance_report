"""``extraction.extension`` — the impure edges: the parsing pipeline.

``ExtractionService`` (vision-LLM + CSV parsing via the format mixins), the
dedup service + ``dual_write_layer`` persistence verbs, brokerage detection /
position import, statement-summary + currency-resolution helpers, the parsing
prompts, and the evidence-graph write path. External numbers enter here and
leave as validated facts (the base layer owns the validation calculus).
"""

from __future__ import annotations
