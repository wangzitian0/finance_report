import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/AppShell";
import ChatWidget from "@/components/ChatWidget";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Finance Report - Personal Finance Management",
  description: "Personal financial management system with double-entry bookkeeping and bank reconciliation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} antialiased`}>
        <AppShell>
          {children}
        </AppShell>
        <ChatWidget />
      </body>
    </html>
  );
}
