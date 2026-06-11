import type { Metadata } from "next";
import type { Viewport } from "next";
import { Analytics } from "@/components/Analytics";
import { AuthGuard } from "@/components/AuthGuard";
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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Read OpenPanel config from runtime (server-side) env. These are plain
  // (non-NEXT_PUBLIC) vars so they are NOT inlined at build time: staging and
  // production share the same promoted Docker image, and each environment
  // supplies its own values via the container `environment:` block at runtime.
  // The server component reads them per request and passes them to the client
  // <Analytics> component, which is a complete no-op when the client id is unset.
  const openpanelClientId = process.env.OPENPANEL_CLIENT_ID;
  const openpanelApiUrl = process.env.OPENPANEL_API_URL;
  const openpanelEnvironment = process.env.OPENPANEL_ENVIRONMENT;

  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <Analytics
          clientId={openpanelClientId}
          apiUrl={openpanelApiUrl}
          environment={openpanelEnvironment}
        />
        <Providers>
          <AuthGuard>
            {children}
          </AuthGuard>
        </Providers>
      </body>
    </html>
  );
}
