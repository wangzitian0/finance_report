"""``common.meta.base`` — the meta package's pure model layer.

Holds :mod:`common.meta.base.package_contract`: the :class:`PackageContract`
aggregate root plus its value objects (``ACRecord``, ``Invariant``, ``Unit``) and
the building-block taxonomy (``Kind`` / ``KIND_LAYER``). Pure, stdlib + pydantic
only — the downward-DAG core the gate (``extension``) and the projection
(``data``) build on. ``base`` never imports ``extension`` or ``data``.
"""
