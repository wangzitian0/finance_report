"""``common.meta.data`` — the meta package's read-model / projection layer.

Holds :mod:`common.meta.data.projection`: pure projections that fold a set of
package contracts (see
:class:`~common.meta.base.package_contract.PackageContract`) into the computed
meta-index (registry, AC index, reverse-dependency consumers, and per-package unit
fan-out by layer), the concept index, and the AC-to-vision-anchor index.

``data`` is a **sink**: it imports only ``base`` (the model) and is imported by no
other layer — nothing in ``base`` or ``extension`` may depend on the read model.
That one-way edge is what the governance gate's ``_check_data_is_sink`` enforces.
"""
