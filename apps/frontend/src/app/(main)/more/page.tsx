"use client";

import Link from "next/link";
import { ChevronRight, LogOut } from "lucide-react";

import { advancedItems, moreItems, type NavItem } from "@/components/navigation";
import { PageHeader } from "@/components/ui";
import { useLogout } from "@/hooks/useLogout";

export default function MorePage() {
  const { handleLogout, isLoggingOut, logoutError } = useLogout();

  const renderRow = (item: NavItem) => {
    const Icon = item.icon;
    return (
      <Link key={item.href} href={item.href} className="card flex items-center gap-3 p-4 transition-colors hover:bg-[var(--background-muted)]">
        <Icon className="h-5 w-5 flex-shrink-0 text-[var(--accent)]" aria-hidden="true" />
        <span className="flex-1 font-medium">{item.label}</span>
        <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />
      </Link>
    );
  };

  return (
    <div className="p-6">
      <PageHeader title="More" description="Everything else — investments, settings, and advanced tools." />
      <div className="mt-4 space-y-2">{moreItems.map(renderRow)}</div>
      <h2 className="mt-6 mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Advanced</h2>
      <div className="space-y-2">{advancedItems.map(renderRow)}</div>
      <button
        type="button"
        onClick={handleLogout}
        disabled={isLoggingOut}
        className="mt-6 flex w-full items-center gap-3 rounded-md px-4 py-3 text-sm font-medium text-[var(--error)] hover:bg-[var(--error-muted)] min-h-[44px]"
      >
        <LogOut className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
        Logout
      </button>
      {logoutError && <p role="alert" className="text-sm text-[var(--error)]">{logoutError}</p>}
    </div>
  );
}
