import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";
beforeEach(() => vi.unstubAllEnvs());
afterEach(() => vi.unstubAllEnvs());
it.each([
  [
    {
      OPENPANEL_API_URL: "",
      OPENPANEL_SCRIPT_URL: "",
      EXTRA_CSP_SCRIPT_SRC: "",
      EXTRA_CSP_CONNECT_SRC: "",
    },
    [
      "script-src 'self' 'unsafe-inline' https://api.openpanel.dev",
      "connect-src 'self' https://api.openpanel.dev",
    ],
    ["zitian.party"],
  ],
  [
    {
      OPENPANEL_API_URL: "https://openpanel.zitian.party/api",
      OPENPANEL_SCRIPT_URL: "https://openpanel.zitian.party/op1.js",
    },
    [
      "https://openpanel.zitian.party",
      /script-src [^;]*https:\/\/openpanel\.zitian\.party/,
      /connect-src [^;]*https:\/\/openpanel\.zitian\.party/,
    ],
    [],
  ],
  [
    {
      NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT:
        "https://otel.zitian.party/v1/traces",
      NEXT_PUBLIC_API_URL: "https://api.zitian.party",
    },
    [
      /connect-src [^;]*https:\/\/otel\.zitian\.party/,
      /connect-src [^;]*https:\/\/api\.zitian\.party/,
    ],
    [],
  ],
  [{ NODE_ENV: "development" }, ["'unsafe-eval'"], []],
  [
    {
      NODE_ENV: "production",
      EXTRA_CSP_SCRIPT_SRC: "'unsafe-eval' https://custom.script.test",
    },
    ["https://custom.script.test"],
    ["'unsafe-eval'"],
  ],
] as const)("AC1.10.4 CSP #%#", (env, inc, exc) => {
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  const csp =
    middleware(new NextRequest("http://localhost:3000/")).headers.get(
      "Content-Security-Policy",
    ) ?? "";
  expect(csp).toBeTruthy();
  for (const p of inc)
    typeof p === "string" ? expect(csp).toContain(p) : expect(csp).toMatch(p);
  for (const x of exc) expect(csp).not.toContain(x);
});
