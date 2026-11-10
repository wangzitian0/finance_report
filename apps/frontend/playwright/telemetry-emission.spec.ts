import { expect, test, type Request } from "@playwright/test"; const OTLP_TRACES_PATH = "/v1/traces"; const OPENPANEL_API_GLOB = "**/openpanel-api/**"; const OPENPANEL_SCRIPT_GLOB = "**/openpanel-op1.js**"; const OPENPANEL_SDK_STUB = `
(function () {
// Same-origin api path so the app CSP (connect-src 'self') permits the POST.
var api = "/openpanel-api";
function emit(name, args) {
try {
fetch(api + "/track", {
method: "POST",
headers: { "content-type": "application/json" },
body: JSON.stringify({ name: name, args: args }),
keepalive: true,
});
} catch (e) {}
}
var queued = (window.op && window.op.q) || [];
// Replace the bootstrap queue proxy with a live dispatcher.
window.op = function () {
var args = [].slice.call(arguments);
emit(args[0], args.slice(1));
};
queued.forEach(function (cmd) {
emit(cmd[0], cmd.slice(1));
// The real SDK auto-tracks a screen view once initialized.
if (cmd[0] === "init") {
emit("screen_view", [{ __path: location.pathname, __title: document.title }]);
}
});
})();
`; test.describe("AC24.2 FE telemetry + analytics emission (#1169)", () => { test("emits a browser OTel span as an OTLP POST to the /v1/traces endpoint (AC24.2.1) and dispatches an OpenPanel event via window.op (AC24.2.2)", async ({ page, }) => { const otlpRequests: Request[] = []; const openpanelEventRequests: Request[] = []; await page.route(`**${OTLP_TRACES_PATH}`, async (route) => { if (route.request().method() === "POST") { otlpRequests.push(route.request()); }; await route.fulfill({ status: 200, contentType: "application/json", body: "{}" }); }); await page.route(OPENPANEL_SCRIPT_GLOB, async (route) => { await route.fulfill({ status: 200, contentType: "text/javascript", body: OPENPANEL_SDK_STUB, }); }); await page.route(OPENPANEL_API_GLOB, async (route) => { if (route.request().method() === "POST") { openpanelEventRequests.push(route.request()); }; await route.fulfill({ status: 202, contentType: "application/json", body: "{}" }); }); await page.addInitScript(() => { localStorage.setItem("finance_user_id", "telemetry-e2e-user"); localStorage.setItem("finance_user_email", "telemetry-e2e@example.com"); }); await page.route("**/api/**", async (route) => { await route.fulfill({ status: 200, contentType: "application/json", body: "{}" }); }); await page.goto("/", { waitUntil: "domcontentloaded" }); await expect .poll(() => page.evaluate(() => typeof (window as unknown as { op?: unknown }).op)) .toBe("function"); await expect .poll(() => openpanelEventRequests.length, { timeout: 15_000 }) .toBeGreaterThan(0); await page.evaluate(() => { void fetch("/api/workflow/status").catch(() => {}); void fetch("/api/statements").catch(() => {}); }); await expect .poll(() => otlpRequests.length, { timeout: 20_000 }) .toBeGreaterThan(0); const traceReq = otlpRequests[0]; expect(new URL(traceReq.url()).pathname).toBe(OTLP_TRACES_PATH); expect(traceReq.method()).toBe("POST"); expect(traceReq.postData() ?? traceReq.postDataBuffer()).toBeTruthy(); }); }); // EPIC-024
