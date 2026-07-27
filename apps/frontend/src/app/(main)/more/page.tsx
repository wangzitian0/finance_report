"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, LogOut } from "lucide-react";

import {
  advancedItems,
  moreItems,
  type NavItem,
} from "@/components/navigation";
import { PageHeader } from "@/components/ui";
import { apiOperation } from "@/lib/api-client";
import { clearUser } from "@/lib/auth";
import type { HoldingsListResponse } from "@/lib/types";

// EPIC-022 AC22.21.5: the More overflow holds low-frequency destinations. The
// Portfolio entry is shown only when the user actually holds securities, so a
// non-investor never sees an empty investment surface.
export default function MorePage() {
  const router = useRouter();
  const [hasHoldings, setHasHoldings] = useState(false);

  useEffect(() => {
    let active = true;
    apiOperation("get_holdings_portfolio_holdings_get")
      .then((data) => {
        const list = data.items ?? [];
        if (active) setHasHoldings(list.length > 0);
      })
      .catch(() => {
        if (active) setHasHoldings(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Gate by the stable route, not the display label, so renaming the label
  // can never silently change the holdings gating.
  const visibleMoreItems = moreItems.filter(
    (item) => item.href !== "/portfolio" || hasHoldings,
  );

  const renderRow = (item: NavItem) => {
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={item.href}
        className="card flex items-center gap-3 p-4 transition-colors hover:bg-[var(--background-muted)]"
      >
        <Icon
          className="h-5 w-5 flex-shrink-0 text-[var(--accent)]"
          aria-hidden="true"
        />
        <span className="flex-1 font-medium">{item.label}</span>
        <ChevronRight
          className="h-4 w-4 flex-shrink-0 text-muted"
          aria-hidden="true"
        />
      </Link>
    );
  };

  const handleLogout = () => {
    clearUser();
    router.push("/login");
  };

  return (
    <div className="p-6">
      <PageHeader
        title="More"
        description="Everything else — investments, settings, and advanced tools."
      />

      <div className="mt-4 space-y-2">{visibleMoreItems.map(renderRow)}</div>

      <h2 className="mt-6 mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Advanced
      </h2>
      <div className="space-y-2">{advancedItems.map(renderRow)}</div>

      <button
        type="button"
        onClick={handleLogout}
        className="mt-6 flex w-full items-center gap-3 rounded-md px-4 py-3 text-sm font-medium text-[var(--error)] hover:bg-[var(--error-muted)] min-h-[44px]"
      >
        <LogOut className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
        Logout
      </button>
    </div>
  );
}
