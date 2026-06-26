"""``common.meta.data`` — the meta package's read-model / projection layer.

Holds :mod:`common.meta.data.projection`: :func:`contract_index`, a pure
projection that folds a set of :class:`~common.meta.base.package_contract.PackageContract`
s into the computed meta-index (registry, AC index, reverse-dependency consumers,
and per-package unit fan-out by layer).

``data`` is a **sink**: it imports only ``base`` (the model) and is imported by no
other layer — nothing in ``base`` or ``extension`` may depend on the read model.
That one-way edge is what the governance gate's ``_check_data_is_sink`` enforces.
"""
