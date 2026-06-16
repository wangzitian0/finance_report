import type { Metadata } from "next";
import type { Viewport } from "next";
import { Analytics } from "@/components/Analytics";
import { AuthGuard } from "@/components/AuthGuard";
import { FrontendTelemetry } from "@/components/FrontendTelemetry";
import { analyticsClientIdMissingInDeployedEnv } from "@/lib/analytics-env";
import { Inter } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Finance Report",
  description: "Personal financial management",
  manifest: "/site.webmanifest",
  icons: {
    icon: "/icon.svg",
    apple: "/apple-touch-icon.png",
  },
  appleWebApp: {
    capable: true,
    title: "Finance Report",
    statusBarStyle: "default",
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#7c3aed",
};

// Read OpenPanel config at request time (server-side), not build time. These are
// plain (non-NEXT_PUBLIC) vars so they are NOT inlined into the client bundle:
// staging and production share the same promoted image, and each environment
// supplies its own values via the container `environment:` block at runtime.
// `force-dynamic` opts the root segment out of static pre-render so the env is
// read per request rather than captured at build (the finance app is auth-gated
// and already effectively dynamic).
export const dynamic = "force-dynamic";

// `force-dynamic` runs RootLayout per request, so log the misconfig at most once
// per server process (mirrors the module-level guard in lib/api.ts) to avoid
// flooding container logs / SigNoz on every request.
let analyticsMisconfigWarned = false;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Gate entirely on the client id: when unset, no <Analytics> (and no extra
  // client boundary / analytics bundle) is rendered at all — a complete no-op.
  const openpanelClientId = process.env.OPENPANEL_CLIENT_ID?.trim();

  if (
    !analyticsMisconfigWarned &&
    analyticsClientIdMissingInDeployedEnv(openpanelClientId, process.env.NEXT_PUBLIC_APP_URL)
  ) {
    analyticsMisconfigWarned = true;
    console.error(
      `[observability] OPENPANEL_CLIENT_ID is empty for ${process.env.NEXT_PUBLIC_APP_URL}; ` +
        "page-view analytics is disabled. infra2 must issue the OpenPanel client id for this environment.",
    );
  }

  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        {openpanelClientId ? (
          <Analytics
            clientId={openpanelClientId}
            apiUrl={process.env.OPENPANEL_API_URL}
            scriptUrl={process.env.OPENPANEL_SCRIPT_URL}
            environment={process.env.OPENPANEL_ENVIRONMENT}
          />
        ) : null}
        {/* Browser OTel → SigNoz. A complete no-op until
            NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT is set; mounts once,
            never blocks render. */}
        <FrontendTelemetry />
        <Providers>
          <AuthGuard>
            {children}
          </AuthGuard>
        </Providers>
      </body>
    </html>
  );
}
