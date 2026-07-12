"""``reporting.data`` — the read-model sink (reserved).

The contract declares the reporting projections (``ReportSnapshotProjection``,
``ReportReadinessProjection``, ``ReportTraceabilityProjection``,
``AccountLineageTreeProjection``, ``ConfidenceTierAggregationProjection``,
``FrameworkPolicyDecisionProjection``) as units with no module path yet; their
physical read-model split lands here in a later slice. Nothing in ``base/`` or
``extension/`` may import this layer.
"""
