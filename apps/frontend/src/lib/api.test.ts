import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  apiOperation,
  apiOperationDownload,
  apiOperationUpload,
  apiOperationStream,
  API_URL,
  resetRedirectGuard,
  ApiError,
} from './api';

// Mock fetch global
const fetchMock = vi.fn();
global.fetch = fetchMock;

// Create a mock localStorage
const localStorageMock = {
  getItem: vi.fn((_key?: string): string | null => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(),
};
Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
  writable: true,
  configurable: true,
});

// Create a mutable mock location object
const mockLocation = { href: '', pathname: '/dashboard' };

// Mock window.location using Object.defineProperty
Object.defineProperty(window, 'location', {
  value: mockLocation,
  writable: true,
  configurable: true,
});

describe('apiOperation transport & errors', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    mockLocation.pathname = '/dashboard';
    localStorageMock.getItem.mockReturnValue(null);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ base_currency: 'SGD' }),
    });
  });

  it('normalizes path and appends query string', async () => {
    await apiOperation('get_holding_dividends_portfolio__ticker__dividends_get', {
      path: { ticker: 'AAPL' },
      query: { limit: 10 },
    });

    const expectedUrl = `${API_URL}/api/portfolio/AAPL/dividends?limit=10`;
    expect(fetchMock).toHaveBeenCalledWith(
      expectedUrl,
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
      }),
    );
  });

  it('serializes array query params and handles missing query', async () => {
    await apiOperation('get_base_currency_app_config_base_currency_get');

    const expectedUrl = `${API_URL}/api/app-config/base-currency`;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it('handles query with null/undefined values', async () => {
    await apiOperation('get_holding_dividends_portfolio__ticker__dividends_get', {
      path: { ticker: 'MSFT' },
      query: { limit: 5, offset: undefined, filter: null } as any,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/portfolio/MSFT/dividends?limit=5'),
      expect.anything(),
    );
  });

  it('throws on missing path parameter', async () => {
    await expect(
      apiOperation('get_holding_dividends_portfolio__ticker__dividends_get', {
        path: { ticker: undefined as any },
      }),
    ).rejects.toThrow('Missing OpenAPI path parameter: ticker');
  });

  it('AC16.10.5 redirects to /login on 401 unauthorized error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    });

    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
  });

  it('throws on 500 server error without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: 'Internal server error' }),
    });

    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('Internal server error');
    expect(mockLocation.href).toBe('');
  });

  it('throws on 404 not found without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ detail: 'Not found' }),
    });

    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('Not found');
    expect(mockLocation.href).toBe('');
  });

  it('falls back to raw text when body is non-json', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => 'plain text error',
    });

    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('plain text error');
  });

  it('handles SSR window undefined guard in handle401Redirect', async () => {
    const oldWindow = (globalThis as { window?: unknown }).window;
    vi.stubGlobal('window', undefined);

    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'no' }),
    });

    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('Authentication required');

    vi.stubGlobal('window', oldWindow);
  });

  it('handle401Redirect handles window.location.href throwing', async () => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      get() {
        return {
          pathname: '/dashboard',
          set href(_val: string) {
            throw new Error('navigation blocked');
          },
        };
      },
    });

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    });

    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('Authentication required - redirect failed');

    Object.defineProperty(window, 'location', {
      value: mockLocation,
      writable: true,
      configurable: true,
    });
  });

  it('handles 204 No Content, tokens, and complex error payloads', async () => {
    localStorageMock.getItem.mockReturnValue('token-xyz');
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
    });

    const res = await apiOperation('delete_account_accounts__account_id__delete', {
      path: { account_id: 'a1' },
    });
    expect(res).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/accounts/a1'),
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({
          Authorization: 'Bearer token-xyz',
        }),
      }),
    );

    // 422 Validation error where detail is array
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: async () =>
        JSON.stringify({
          detail: [{ loc: ['body', 'name'], msg: 'Field required' }],
          error_id: 'validation_error',
          request_id: 'req-v1',
        }),
    });

    let caughtErr: any;
    try {
      await apiOperation('create_account_accounts_post', {
        body: { name: '', type: 'ASSET' as any, currency: 'SGD' },
      });
    } catch (err) {
      caughtErr = err;
    }
    expect(caughtErr).toBeInstanceOf(ApiError);
    expect(caughtErr.errorId).toBe('validation_error');
    expect(caughtErr.requestId).toBe('req-v1');
    expect(caughtErr.message).toContain('Field required');

    // JSON primitive parsed
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => '12345',
    });
    await expect(
      apiOperation('get_base_currency_app_config_base_currency_get'),
    ).rejects.toThrow('12345');
  });

  it('DELETE operation redirects on 401 with token', async () => {
    localStorageMock.getItem.mockReturnValue('del-token');
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'forbidden',
    });

    await expect(
      apiOperation('delete_account_accounts__account_id__delete', {
        path: { account_id: 'delete-me' },
      }),
    ).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/accounts/delete-me'),
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({
          Authorization: 'Bearer del-token',
        }),
      }),
    );
  });
});

describe('apiOperationStream', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('streams with query, headers, and token', async () => {
    localStorageMock.getItem.mockReturnValue('mock-token');
    const mockHeaders = {
      get: (header: string) =>
        header.toLowerCase() === 'x-session-id' ? 'sess-123' : null,
    };
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: mockHeaders,
      text: async () => '',
    });

    const result = await apiOperationStream('chat_message_chat_post', {
      body: { message: 'hello' } as any,
    });

    expect(result.sessionId).toBe('sess-123');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/chat'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer mock-token',
        }),
      }),
    );
  });

  it('redirects on 401', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'unauthorized' }),
    });

    await expect(
      apiOperationStream('chat_message_chat_post', {
        body: { message: 'hi' } as any,
      }),
    ).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
  });

  it('throws ApiError on non-401 failure', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () =>
        JSON.stringify({
          detail: 'LLM crashed',
          error_id: 'llm_error',
          request_id: 'req-1',
        }),
    });

    await expect(
      apiOperationStream('chat_message_chat_post', {
        body: { message: 'hi' } as any,
      }),
    ).rejects.toThrow('LLM crashed');
  });
});

describe('apiOperationDownload', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('downloads and parses various Content-Disposition headers', async () => {
    localStorageMock.getItem.mockReturnValue('mock-token');
    const csvBlob = new Blob(['col1,col2\nval1,val2\n'], { type: 'text/csv' });
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: {
        get: (h: string) =>
          h.toLowerCase() === 'content-disposition'
            ? "attachment; filename*=UTF-8''report%202026.csv"
            : null,
      },
    });

    const result = await apiOperationDownload(
      'export_report_reports_export_get',
      {
        query: { report_type: 'cash-flow' } as any,
      },
    );

    expect(result.blob).toBe(csvBlob);
    expect(result.filename).toBe('report 2026.csv');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/reports/export'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer mock-token',
        }),
      }),
    );
  });

  it('handles malformed UTF-8 and missing header in Content-Disposition', async () => {
    const csvBlob = new Blob(['data'], { type: 'text/csv' });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: {
        get: (h: string) =>
          h.toLowerCase() === 'content-disposition'
            ? "attachment; filename*=UTF-8''%E0%A4%A"
            : null,
      },
    });

    const res1 = await apiOperationDownload(
      'export_report_reports_export_get',
      { query: {} as any },
    );
    expect(res1.filename).toBe('%E0%A4%A');

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: { get: () => null },
    });
    const res2 = await apiOperationDownload(
      'export_report_reports_export_get',
      { query: {} as any },
    );
    expect(res2.filename).toBeNull();

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: {
        get: (h: string) =>
          h.toLowerCase() === 'content-disposition'
            ? 'attachment; filename=plain_report.csv'
            : null,
      },
    });
    const res3 = await apiOperationDownload(
      'export_report_reports_export_get',
      { query: {} as any },
    );
    expect(res3.filename).toBe('plain_report.csv');
  });

  it('throws and redirects on 401, throws on 500', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    });

    await expect(
      apiOperationDownload('export_report_reports_export_get', {
        query: {} as any,
      }),
    ).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => 'export failed',
    });
    await expect(
      apiOperationDownload('export_report_reports_export_get', {
        query: {} as any,
      }),
    ).rejects.toThrow('export failed');

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: async () =>
        JSON.stringify({ detail: 'No such report', error_id: 'not_found', request_id: 'req-d1' }),
    });
    const err = await apiOperationDownload('export_report_reports_export_get', {
      query: {} as any,
    }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 404, errorId: 'not_found', requestId: 'req-d1' });
  });
});

describe('apiOperationUpload', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('uploads a FormData body with token and handles 204', async () => {
    localStorageMock.getItem.mockReturnValue('mock-token');
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: 'stmt-new', original_filename: 'test.pdf' }),
    });

    const fd = new FormData();
    fd.append('file', new Blob(['fake pdf']), 'test.pdf');

    const result = await apiOperationUpload(
      'upload_statement_statements_upload_post',
      {
        body: fd,
      },
    );

    expect(result).toEqual({ id: 'stmt-new', original_filename: 'test.pdf' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/statements/upload'),
      expect.objectContaining({
        method: 'POST',
        body: fd,
        headers: expect.objectContaining({
          Authorization: 'Bearer mock-token',
        }),
      }),
    );

    // 204 No content returns undefined
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
    });
    const res204 = await apiOperationUpload(
      'upload_statement_statements_upload_post',
      { body: fd },
    );
    expect(res204).toBeUndefined();
  });

  it('throws on 401 and 400 error', async () => {
    const fd = new FormData();
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'need login',
    });

    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', {
        body: fd,
      }),
    ).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: async () =>
        JSON.stringify({
          detail: 'bad file format',
          error_id: 'bad_format',
        }),
    });
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', {
        body: fd,
      }),
    ).rejects.toThrow('bad file format');
  });
});
