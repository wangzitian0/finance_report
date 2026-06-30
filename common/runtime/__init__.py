"""``runtime`` — the app↔external-world dependency boundary (draft).

Spec-only for now: this package owns the *contract* for how the application
depends on external backends (object storage, the LLM provider, cache, telemetry,
…), how each environment substitutes them, and how their presence is asserted.
No curated symbol language yet (``contract.interface == []``); see ``readme.md``.
"""
