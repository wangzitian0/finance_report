"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { apiOperation } from "@/lib/api-client";
import { HoldingsListResponse } from "@/lib/types";
import { PriceUpdateForm } from "@/components/portfolio/PriceUpdateForm";

export default function PricesPage() {
  const { data: holdings, refetch } = useQuery({
    queryKey: ["portfolio-holdings-for-prices"],
    queryFn: () =>
      apiOperation("get_holdings_portfolio_holdings_get").then(
        (response) => response.items,
      ),
  });

  const knownTickers = holdings
    ? [...new Set(holdings.map((h) => h.asset_identifier))].sort()
    : [];

  return (
    <div className="p-6">
      <div className="mb-4">
        <Link
          href="/portfolio"
          className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 19l-7-7 7-7"
            />
          </svg>
          Back to Portfolio
        </Link>
      </div>

      <div className="page-header">
        <h1 className="page-title">Update Market Prices</h1>
        <p className="page-description">
          Manually update market prices for your holdings to see current
          valuations
        </p>
      </div>

      <div className="card">
        <div className="card-header">
          <h2 className="text-sm font-medium">Batch Price Update</h2>
        </div>
        <div className="p-6">
          <PriceUpdateForm
            knownTickers={knownTickers}
            onSuccess={() => refetch()}
          />
        </div>
      </div>
    </div>
  );
}
