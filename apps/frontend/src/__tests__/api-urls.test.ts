import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("API URL and CSP configuration", () => {
  const original = process.env.NEXT_PUBLIC_API_URL;
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_API_URL", original));
  afterEach(() => vi.unstubAllEnvs());

  it("AC7.9.5 AC1.10.4 avoids localhost rewrites in production and sets security headers", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://report.example.com");
    vi.stubEnv("NODE_ENV", "production");
    const { default: cfg } = await import("../../next.config.mjs");
    expect(JSON.stringify(await cfg.rewrites?.())).not.toContain("localhost:8000");

    const rules = (await cfg.headers?.()) ?? [];
    const h = Object.fromEntries(rules.flatMap((r: { headers: Array<{ key: string; value: string }> }) => r.headers.map((x) => [x.key, x.value])));
    expect(h["Content-Security-Policy"]).toContain("default-src 'self'");
    expect(h["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
    expect(h["Content-Security-Policy"]).not.toContain("'unsafe-eval'");
    expect(h["Strict-Transport-Security"]).toContain("max-age=31536000");
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(h["Permissions-Policy"]).toContain("camera=()");
  });

  it.each([
    [{}, [/script-src/, /https:\/\/api\.openpanel\.dev/], [/zitian\.party/]],
    [{ EXTRA_CSP_CONNECT_SRC: "https://*.zitian.party" }, [/connect-src [^;]*https:\/\/\*\.zitian\.party/], []],
    [{ OPENPANEL_API_URL: "https://op.example.com/v1", OPENPANEL_SCRIPT_URL: "https://cdn.example.com/t.js" }, [/script-src [^;]*https:\/\/op\.example\.com/, /connect-src [^;]*https:\/\/op\.example\.com/, /script-src [^;]*https:\/\/cdn\.example\.com/], []],
    [{ EXTRA_CSP_CONNECT_SRC: "https://s1.example.com; https://s2.example.com;", EXTRA_CSP_SCRIPT_SRC: "https://sc.example.com;" }, [/connect-src [^;]*https:\/\/s1\.example\.com/, /connect-src [^;]*https:\/\/s2\.example\.com/, /script-src [^;]*https:\/\/sc\.example\.com/], []],
    [{ OPENPANEL_API_URL: "data:text/plain;base64,SGVsbG8=" }, [], [/null/]],
    [{ EXTRA_CSP_CONNECT_SRC: "bad 'self' data:text/plain;base64,abc https://ok.example.com/p", EXTRA_CSP_SCRIPT_SRC: "badtok 'unsafe-eval' https://okjs.example.com" }, [/https:\/\/ok\.example\.com/, /https:\/\/okjs\.example\.com/, /'unsafe-eval'/], [/badtok/, /connect-src [^;]*data:/]],
    [{ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "https://otel.zitian.party/v1/traces", NEXT_PUBLIC_API_URL: "https://api.example.com" }, [/connect-src [^;]*https:\/\/otel\.zitian\.party/, /connect-src [^;]*https:\/\/api\.example\.com/], []],
  ] as const)("builds CSP for %o", async (envs, matches, excludes) => {
    for (const [k, v] of Object.entries(envs)) vi.stubEnv(k, v);
    const { buildContentSecurityPolicy } = await import("../../next.config.mjs");
    const csp = buildContentSecurityPolicy();
    for (const re of matches) expect(csp).toMatch(re);
    for (const re of excludes) expect(csp).not.toMatch(re);
  });
});
