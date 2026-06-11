import { describe, expect, it } from "vitest";

// EPIC-022 route alignment is enforced through Next.js redirects so legacy
// bookmarks and in-app deep links land on the everyday-user IA.
import nextConfig from "../../next.config.mjs";

async function redirectMap() {
  const redirects = (await nextConfig.redirects?.()) ?? [];
  return new Map(
    redirects.map((rule: { source: string; destination: string }) => [rule.source, rule.destination]),
  );
}

describe("next.config redirects (EPIC-022 route alignment)", () => {
  it("AC22.1.4 redirects the legacy dashboard route to Home", async () => {
    const map = await redirectMap();
    expect(map.get("/dashboard")).toBe("/");
    // `/` must NOT be redirected anymore — it renders the smart Home in-shell.
    expect(map.has("/")).toBe(false);
  });

  it("AC22.1.5 redirects /events to /notifications", async () => {
    const map = await redirectMap();
    expect(map.get("/events")).toBe("/notifications");
  });

  it("AC22.1.6 redirects /assets to /portfolio", async () => {
    const map = await redirectMap();
    expect(map.get("/assets")).toBe("/portfolio");
  });

  it("AC22.1.8 redirects legacy statement routes to /upload", async () => {
    const map = await redirectMap();
    expect(map.get("/statements/upload")).toBe("/upload");
    expect(map.get("/statements")).toBe("/upload");
  });
});
