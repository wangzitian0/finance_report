import type { Metadata } from "next";
import { AuthGuard } from "@/components/AuthGuard";
import { Sidebar } from "@/components/Sidebar";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { AppShell } from "@/components/AppShell";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata = {
  title: "Finance Report",
  description: "Personal financial management",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <AuthGuard>
          <AppShell>
            <div className="flex h-screen bg-[var(--background)]">
              <Sidebar />
              <main className="flex-1 flex flex-col min-w-0 transition-all duration-300 ease-in-out bg-[var(--background)]">
                <WorkspaceTabs />
                <div className="flex-1 overflow-auto">
                  {children}
                </div>
              </main>
            </div>
          </AppShell>
        </AuthGuard>
      </body>
    </html>
  );
}
