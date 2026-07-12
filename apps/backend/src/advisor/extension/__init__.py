"""``advisor.extension`` — domain services, ports, and I/O edges.

Holds :class:`AIAdvisorService` (context aggregation → prompt construction →
guarded streaming), the :class:`ResponseCache`, the annualized-income
schedule, and the ``app_reads`` injection ports for reads whose owners still
live in the un-migrated app remainder.
"""
