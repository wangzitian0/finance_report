import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProcessingTransfers } from '@/components/statements/ProcessingTransfers';
import { ProcessingSummaryCard } from '@/components/audit/TrustScoreHero';
import { apiOperation } from '@/lib/api-client';
import { PROCESSING_PENDING_QUERY_KEY } from '@/lib/sharedQueries';
import type { ReactNode } from 'react';

const navigationState = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

function renderTransfers() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}><ProcessingTransfers /></QueryClientProvider>) };
}

vi.mock('@/lib/api-client', () => ({
  apiOperation: vi.fn(),
}));

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => navigationState.searchParams,
}));

vi.mock("@/components/charts/BarChart", () => ({
  BarChart: () => <div>BarChartMock</div>,
}))

vi.mock("@/components/charts/PieChart", () => ({
  PieChart: () => <div>PieChartMock</div>,
}))

vi.mock("@/components/charts/TrendChart", () => ({
  TrendChart: () => <div>TrendChartMock</div>,
}))

vi.mock("@/components/charts/NetWorthTimeSeriesChart", () => ({
  NetWorthTimeSeriesChart: () => <div>NetWorthTimeSeriesMock</div>,
}))

describe('EPIC-015 / UI Gap Audit / Processing Account Visibility', () => {
  const mockedApiOperation = vi.mocked(apiOperation);

  beforeEach(() => {
    mockedApiOperation.mockReset();
    navigationState.searchParams = new URLSearchParams();
  });

  it('AC15.7.1 — GET /api/accounts/processing/summary contract', async () => {
    mockedApiOperation.mockResolvedValue({
      pending_count: 1,
      pending_total: "100.00",
      current_balance: "100.00",
      currency: "SGD",
      oldest_pending_date: "2026-05-01"
    });

    render(<ProcessingSummaryCard />);

    await waitFor(() => {
      expect(mockedApiOperation).toHaveBeenCalledWith('get_processing_summary_accounts_processing_summary_get', expect.anything());
    });
  });

  // AC-ledger.fe-processing.1
  it('AC15.7.2 / AC15.7.8 — ProcessingSummaryCard renders fields and current balance warning', async () => {
    mockedApiOperation.mockResolvedValue({
      pending_count: 3,
      pending_total: "150.00",
      current_balance: "150.00",
      currency: "SGD",
      oldest_pending_date: "2026-04-15"
    });

    render(<ProcessingSummaryCard />);

    await waitFor(() => {
      expect(screen.getByTestId('processing-count')).toHaveTextContent('3 Pending');
      expect(screen.getByTestId('processing-balance')).toHaveTextContent(/150/);
      expect(screen.getByLabelText(/unresolved processing account balance/i)).toBeInTheDocument();
      expect(screen.getByText(/150/)).toBeInTheDocument();
      expect(screen.getByText(/Apr 15, 2026/)).toBeInTheDocument();
    });
  });

  // AC-ledger.fe-processing.2
  it('AC15.7.3 — Upload page transfers-in-flight card renders pending transfers', async () => {
    mockedApiOperation.mockResolvedValue({
      items: [
        {
          entry_id: "e1",
          from_account: "Bank A",
          to_account: "Bank B",
          amount: "500.00",
          currency: "SGD",
          initiated_date: "2026-05-01",
          days_outstanding: 2,
          description: "Transfer 1"
        },
        {
          entry_id: "e2",
          from_account: "Bank C",
          to_account: "Bank D",
          amount: "1000.00",
          currency: "SGD",
          initiated_date: "2026-05-02",
          days_outstanding: 1,
          description: "Transfer 2"
        }
      ],
      total: 2
    });

    renderTransfers();

    await waitFor(() => {
      expect(mockedApiOperation).toHaveBeenCalledWith('list_processing_pending_accounts_processing_pending_get', {});
      expect(screen.getByText('Bank A')).toBeInTheDocument();
      expect(screen.getByText('Bank B')).toBeInTheDocument();
      expect(screen.getByText(/500\.00/)).toBeInTheDocument();
      expect(screen.getByText('Bank C')).toBeInTheDocument();
      expect(screen.getByText('Bank D')).toBeInTheDocument();
      expect(screen.getByText(/1,000\.00/)).toBeInTheDocument();
    });
  });

  // AC-ledger.fe-processing.3
  it('AC15.7.4 — warning badge for >7 day pending', async () => {
    mockedApiOperation.mockResolvedValue({
      items: [
        {
          entry_id: "e1",
          from_account: "Bank A",
          to_account: "Bank B",
          amount: "500.00",
          currency: "SGD",
          initiated_date: "2026-04-15",
          days_outstanding: 12,
          description: "Old Transfer"
        }
      ],
      total: 1
    });

    renderTransfers();

    await waitFor(() => {
      const badge = screen.getByLabelText(/warning/i);
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveTextContent('12d');
    });
  });

  it('test_AC8_13_48 — transfers-in-flight card renders load errors', async () => {
    mockedApiOperation.mockRejectedValueOnce(new Error("processing unavailable"));

    renderTransfers();

    expect(await screen.findByText("processing unavailable")).toBeInTheDocument();
  });

  it('AC15.7.3 — transfers-in-flight card renders nothing when no transfer is waiting', async () => {
    mockedApiOperation.mockResolvedValue({ items: [], total: 0 });

    const { container, client } = renderTransfers();

    await waitFor(() => expect(client.getQueryState(PROCESSING_PENDING_QUERY_KEY)?.status).toBe('success'));
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('Transfers in flight')).not.toBeInTheDocument();
  });

  // AC-ledger.fe-processing.4
  it('AC15.7.5 — ProcessingSummaryCard mount test', async () => {
    mockedApiOperation.mockImplementation(((operationId: string) => {
      if (operationId === 'get_processing_summary_accounts_processing_summary_get') {
        return Promise.resolve({ pending_count: 2, pending_total: "200.00", current_balance: "200.00", currency: "SGD", oldest_pending_date: "2026-05-01" });
      }
      if (operationId === 'balance_sheet_reports_balance_sheet_get') {
        return Promise.resolve({ assets: [], total_assets: 0, total_liabilities: 0, currency: "SGD", as_of_date: "2026-05-04", is_balanced: true });
      }
      if (operationId === 'income_statement_reports_income_statement_get') {
        return Promise.resolve({ currency: "SGD", trends: [{ period_start: "2026-01-01", period_end: "2026-01-31", total_income: 1000, total_expenses: 800, net_income: 200 }] });
      }
      if (operationId === 'get_reconciliation_stats_reconciliation_stats_get') {
        return Promise.resolve({ total_transactions: 0, matched_transactions: 0, unmatched_transactions: 0, pending_review: 0, auto_accepted: 0, match_rate: 0, score_distribution: {} });
      }
      if (operationId === 'get_unmatched_transactions_reconciliation_unmatched_get') {
        return Promise.resolve({ items: [], total: 0 });
      }
      if (operationId === 'list_journal_entries_journal_entries_get') {
        return Promise.resolve({ items: [], total: 0 });
      }
      if (operationId === 'trend_reports_trend_get') {
        return Promise.resolve({ points: [], account_id: "a1", currency: "SGD", period: "monthly" });
      }
      if (operationId === 'net_worth_timeseries_reports_net_worth_timeseries_get') {
        return Promise.resolve({ points: [], currency: "SGD" });
      }
      return Promise.resolve({});
    }) as any);

    render(<ProcessingSummaryCard />);

    await waitFor(() => {
      expect(screen.getByTestId('processing-count')).toHaveTextContent('2 Pending');
      expect(screen.getByTestId('processing-balance')).toHaveTextContent(/200/);
    }, { timeout: 2000 });
  });
});
