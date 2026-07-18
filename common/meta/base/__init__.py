"""``common.meta.base`` — the meta package's pure model layer.

Holds :mod:`common.meta.base.package_contract`: the :class:`PackageContract`
aggregate root plus its value objects (``ACRecord``, ``Invariant``, ``Unit``) and
the building-block taxonomy (``Kind`` / ``KIND_LAYER``). It also owns the typed
dependency vocabulary and pure graph policy in
:mod:`common.meta.base.dependency_graph`. Pure, stdlib + pydantic only — the
downward-DAG core the gate (``extension``) and the projection (``data``) build
on. ``base`` never imports ``extension`` or ``data``.
"""
