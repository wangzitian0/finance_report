"""``common.meta.extension`` — the meta package's edge layer.

Holds :mod:`common.meta.extension.check_package_contract`: the governance gate
(a domain service) that walks the filesystem, parses contracts and ``__all__``,
and validates every package against its :class:`~common.meta.base.package_contract.PackageContract`.
It imports ``base`` (the model) — never the other way round (``extension -> base``,
one-way), and never ``data``.
"""
