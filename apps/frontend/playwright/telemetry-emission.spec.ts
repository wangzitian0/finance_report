import { expect, test, type Request } from "@playwright/test";

/**
 * EPIC-024 AC24.2 — real-browser proof that FE telemetry actually EMITS (#1169).
 *
 * Runs under `playwright.telemetry.config.ts`, whose `webServer.env` configures
 * the browser-OTel OTLP endpoint and the OpenPanel client id, so the real root
 * layout mounts `<FrontendTelemetry>` + `<Analytics>` with active config. This
 * spec then asserts, in a real Chromium browser, the two outbound emissions:
 *
 *  - AC24.2.1: the browser OTel SDK POSTs an OTLP payload to the configured
 *    `/v1/traces` collector endpoint.
 *  - AC24.2.2: the OpenPanel analytics layer dispatches a page-view/event
 *    (`window.op` is installed, an `init` command is enqueued, and an outbound
 *    event POST reaches the OpenPanel API).
 *
 * Hermetic: every telemetry destination is intercepted with `page.route` and
 * fulfilled locally — no real OTLP collector, no real OpenPanel cloud, and the
 * `op1.js` SDK script is replaced by a tiny stub that honors the documented
 * `window.op` queue contract. No assertion depends on a real backend being up.
 */

const OTLP_TRACES_PATH = "/v1/traces";
const OPENPANEL_API_GLOB = "**/openpanel-api/**";
const OPENPANEL_SCRIPT_GLOB = "**/openpanel-op1.js**";

// A minimal stand-in for the OpenPanel `op1.js` SDK. It honors the public
// `window.op` queue contract (the init snippet installs a queue at
// `window.op.q`) and emulates the documented behavior: drain queued commands,
// auto-fire a screen-view on init, and POST every event to the OpenPanel API so
// the test can observe a real outbound analytics request.
const OPENPANEL_SDK_STUB = `
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
`;

test.describe("AC24.2 FE telemetry + analytics emission (#1169)", () => {
  test("emits a browser OTel span as an OTLP POST to the /v1/traces endpoint (AC24.2.1) and dispatches an OpenPanel event via window.op (AC24.2.2)", async ({
    page,
  }) => {
    const otlpRequests: Request[] = [];
    const openpanelEventRequests: Request[] = [];

    // Intercept the OTLP collector: capture each export POST, then 200 it so the
    // exporter sees success (no real OTLP collector contacted).
    await page.route(`**${OTLP_TRACES_PATH}`, async (route) => {
      if (route.request().method() === "POST") {
        otlpRequests.push(route.request());
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    // Intercept the OpenPanel SDK script with the queue-honoring stub.
    await page.route(OPENPANEL_SCRIPT_GLOB, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/javascript",
        body: OPENPANEL_SDK_STUB,
      });
    });

    // Intercept every OpenPanel API call (the outbound event POSTs).
    await page.route(OPENPANEL_API_GLOB, async (route) => {
      if (route.request().method() === "POST") {
        openpanelEventRequests.push(route.request());
      }
      await route.fulfill({ status: 202, contentType: "application/json", body: "{}" });
    });

    // Skip auth so the app shell renders without a backend.
    await page.addInitScript(() => {
      localStorage.setItem("finance_user_id", "telemetry-e2e-user");
      localStorage.setItem("finance_user_email", "telemetry-e2e@example.com");
    });
    // Stub backend API so the page renders deterministically.
    await page.route("**/api/**", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    await page.goto("/", { waitUntil: "domcontentloaded" });

    // --- AC24.2.2: OpenPanel analytics emission ---------------------------
    // The bootstrap queue proxy is installed by the inline init snippet.
    await expect
      .poll(() => page.evaluate(() => typeof (window as unknown as { op?: unknown }).op))
      .toBe("function");
    // An outbound OpenPanel event POST actually fired (init/screen_view).
    await expect
      .poll(() => openpanelEventRequests.length, { timeout: 15_000 })
      .toBeGreaterThan(0);

    // --- AC24.2.1: browser OTel OTLP export -------------------------------
    // Drive client-side activity so the FetchInstrumentation/document-load
    // produce spans, then wait for the BatchSpanProcessor to flush an export.
    await page.evaluate(() => {
      // A few client fetches give the fetch-instrumentation spans to export.
      void fetch("/api/workflow/status").catch(() => {});
      void fetch("/api/statements").catch(() => {});
    });
    await expect
      .poll(() => otlpRequests.length, { timeout: 20_000 })
      .toBeGreaterThan(0);

    // The export targeted the configured /v1/traces collector with a payload.
    const traceReq = otlpRequests[0];
    expect(new URL(traceReq.url()).pathname).toBe(OTLP_TRACES_PATH);
    expect(traceReq.method()).toBe("POST");
    expect(traceReq.postData() ?? traceReq.postDataBuffer()).toBeTruthy();
  });
});
