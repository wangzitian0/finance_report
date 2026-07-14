// Shared loader for the backend-owned API response conformance vectors
// (#1827 G-contract-reddens, pattern from #1167 money conformance).
//
// Page tests for the vectored endpoints load their mock data from the SAME
// committed common/<pkg>/conformance/vectors.json files the backend drift
// test recomputes (apps/backend/tests/schemas/test_api_response_vectors.py,
// regenerated only by tools/api_response_vectors.py). A backend serializer
// change therefore reds a gate on one side or the other — it can no longer
// ship green against hand-written frontend JSON.
//
// Every vector value is a sanitized placeholder; never add real financial
// data to the vector files.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type {
  AccountListResponse,
  BalanceSheetResponse,
  BankStatement,
} from "@/lib/types";

const here = dirname(fileURLToPath(import.meta.url));
const commonRoot = resolve(here, "../../../../../common");

type VectorEndpoint = {
  method: string;
  fe_path: string;
  response_model: string;
  response: unknown;
};

type VectorFile = {
  endpoints: Record<string, VectorEndpoint | undefined>;
};

function loadEndpointResponse(pkg: string, endpoint: string): unknown {
  const path = resolve(commonRoot, pkg, "conformance", "vectors.json");
  const file = JSON.parse(readFileSync(path, "utf-8")) as VectorFile;
  const entry = file.endpoints[endpoint];
  if (!entry) {
    throw new Error(
      `endpoint '${endpoint}' is missing from common/${pkg}/conformance/vectors.json — ` +
        "regenerate via apps/backend/.venv/bin/python tools/api_response_vectors.py",
    );
  }
  // Fresh copy per call so a test mutating its mock cannot leak into others.
  return structuredClone(entry.response);
}

/** GET /api/reports/balance-sheet — the committed backend wire shape. */
export function balanceSheetVector(): BalanceSheetResponse {
  return loadEndpointResponse("reporting", "balance_sheet") as BalanceSheetResponse;
}

/** GET /api/accounts — the committed backend wire shape. */
export function accountsListVector(): AccountListResponse {
  return loadEndpointResponse("ledger", "accounts_list") as AccountListResponse;
}

/** POST /api/statements/upload (202) — freshly accepted upload envelope. */
export function statementUploadAcceptedVector(): BankStatement {
  return loadEndpointResponse("extraction", "statement_upload_accepted") as BankStatement;
}

/** GET /api/statements/{id} — the same envelope once parsing settled. */
export function statementParsedVector(): BankStatement {
  return loadEndpointResponse("extraction", "statement_parsed") as BankStatement;
}
