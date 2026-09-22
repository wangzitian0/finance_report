# Single Source of Truth (SSOT) Index

This directory maintains authoritative Single Source of Truth (SSOT) specifications for core domain models, business flows, and accounting guarantees in Finance Report.

---

## Authoritative Specifications

- [**30 Core Wealth & Accounting Flows SSOT**](thirty-wealth-flows.md) (`thirty-wealth-flows.md`)  
  Authoritative specification of the 30 core wealth and accounting flows across 7 canonical domains, including UI routes, frontend components, backend FastAPI endpoints, double-entry invariant rules, and test references.
  - JSON Registry: [`common/meta/flows/thirty_flows_ssot.json`](../../common/meta/flows/thirty_flows_ssot.json)
  - Backend Consistency Suite: [`apps/backend/tests/flows/test_thirty_flows_consistency.py`](../../apps/backend/tests/flows/test_thirty_flows_consistency.py)
  - Frontend Consistency Suite: [`apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx`](../../apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx)

---

## Related References

- [Contract References Overview](../reference/api-overview.md)
- [Generated API Reference](../reference/api.md)
- [Router Contract Maturity](../reference/router-contract-maturity.md)
- [Product Analytics Events](../reference/analytics-events.md)
