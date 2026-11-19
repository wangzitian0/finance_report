import { expect, test, type Request } from "@playwright/test";
import { installApiMocks } from "./helpers";

const STUB = `(function(){function e(n,a){try{fetch("/openpanel-api/track",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({name:n,args:a}),keepalive:true});}catch(_){}}var q=(window.op&&window.op.q)||[];window.op=function(){var a=[].slice.call(arguments);e(a[0],a.slice(1));};q.forEach(function(c){e(c[0],c.slice(1));if(c[0]==="init")e("screen_view",[{__path:location.pathname,__title:document.title}]);});})();`;

test.describe("AC24.2 FE telemetry + analytics emission (#1169)", () => {
  test("emits a browser OTel span as an OTLP POST to the /v1/traces endpoint (AC24.2.1) and dispatches an OpenPanel event via window.op (AC24.2.2)", async ({ page }) => {
    const otlp: Request[] = [], op: Request[] = [];
    await page.route("**/v1/traces", async (r) => { if (r.request().method() === "POST") otlp.push(r.request()); await r.fulfill({ status: 200, contentType: "application/json", body: "{}" }); });
    await page.route("**/openpanel-op1.js**", (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: STUB }));
    await page.route("**/openpanel-api/**", async (r) => { if (r.request().method() === "POST") op.push(r.request()); await r.fulfill({ status: 202, contentType: "application/json", body: "{}" }); });
    await installApiMocks(page, "t", {}); await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect.poll(() => page.evaluate(() => typeof (window as unknown as { op?: unknown }).op)).toBe("function");
    await expect.poll(() => op.length, { timeout: 15_000 }).toBeGreaterThan(0);
    await page.evaluate(() => { void fetch("/api/workflow/status").catch(() => {}); void fetch("/api/statements").catch(() => {}); });
    await expect.poll(() => otlp.length, { timeout: 20_000 }).toBeGreaterThan(0);
    expect(new URL(otlp[0].url()).pathname).toBe("/v1/traces"); expect(otlp[0].method()).toBe("POST"); expect(otlp[0].postData() ?? otlp[0].postDataBuffer()).toBeTruthy();
  });
});
// EPIC-024
