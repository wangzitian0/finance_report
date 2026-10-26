import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProcessingTransfers } from '@/components/statements/ProcessingTransfers';
import { apiOperation } from '@/lib/api-client';
import { PROCESSING_PENDING_QUERY_KEY } from '@/lib/sharedQueries';

function renderTransfers() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}><ProcessingTransfers /></QueryClientProvider>) };
}

vi.mock('@/lib/api-client', () => ({
  apiOperation: vi.fn(),
}));

describe('EPIC-015 / UI Gap Audit / Processing Account Visibility', () => {
  const mockedApiOperation = vi.mocked(apiOperation);

  beforeEach(() => {
    mockedApiOperation.mockReset();
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
});
