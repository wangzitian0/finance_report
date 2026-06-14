/**
 * Typed access to the backend contract (#1004).
 *
 * `api-types.ts` is generated from the backend OpenAPI schema
 * (`apps/frontend/openapi.json`, staleness-gated by
 * `tools/generate_openapi_spec.py --check`). This module re-exports its schema
 * objects under ergonomic aliases so call sites can type requests/responses
 * against the generated contract — e.g. `apiFetch<Schemas["BatchApproveResponse"]>(...)`
 * — giving compile-time FE↔BE drift detection instead of hand-written shapes.
 *
 * Migrate high-traffic modules to these aliases incrementally; do not edit
 * `api-types.ts` by hand (run `npm run gen:api-types`).
 */
import type { components, paths } from "./api-types";

/** All generated request/response models, keyed by their backend schema name. */
export type Schemas = components["schemas"];

/** All generated API paths/operations, for path-level typing when needed. */
export type Paths = paths;
