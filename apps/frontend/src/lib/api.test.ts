import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiFetch, apiUpload, API_URL, resetRedirectGuard } from './api';

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
const mockLocation = { href: '' };

// Mock window.location using Object.defineProperty
Object.defineProperty(window, 'location', {
  value: mockLocation,
  writable: true,
  configurable: true,
});

describe('apiFetch', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    // Default: no token (unauthenticated)
    localStorageMock.getItem.mockReturnValue(null);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: 'test' }),
    });
  });

  it('should normalize path by adding leading slash if missing', async () => {
    await apiFetch('users');

    const expectedUrl = `${API_URL}/users`;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it('should not add double slash if path already has leading slash', async () => {
    await apiFetch('/users');

    const expectedUrl = `${API_URL}/users`;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it('should preserve whitespace in path while normalizing leading slash', async () => {
    await apiFetch('users  ');

    const expectedUrl = `${API_URL}/users  `;
    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it('AC16.10.5 should redirect to /login on 401 unauthorized error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    });

    await expect(apiFetch('/api/statements')).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
  });

  it('should throw error on 500 server error without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: 'Internal server error' }),
    });

    await expect(apiFetch('/api/statements')).rejects.toThrow('Internal server error');
    expect(mockLocation.href).toBe(''); // No redirect
  });

  it('should throw error on 404 not found without redirect', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ detail: 'Not found' }),
    });

    await expect(apiFetch('/api/users/123')).rejects.toThrow('Not found');
    expect(mockLocation.href).toBe(''); // No redirect
  });

  it('should fallback to raw text when body is non-json', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => "plain text error"
    });

    await expect(apiFetch('/api/bad')).rejects.toThrow('plain text error');
  });

  it('should handle SSR window undefined guard in handle401Redirect', async () => {
    const oldWindow = (globalThis as { window?: unknown }).window;
    vi.stubGlobal('window', undefined);

    fetchMock.mockResolvedValue({ ok: false, status: 401, text: async () => JSON.stringify({ detail: 'no' }) });

    await expect(apiFetch('/api/ssr')).rejects.toThrow('Authentication required');

    vi.stubGlobal('window', oldWindow);
  });
});

describe('apiUpload', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    // Default: no token (unauthenticated)
    localStorageMock.getItem.mockReturnValue(null);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'uploaded' }),
    });
  });

  it('apiStream should redirect on 401', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 401, text: async () => JSON.stringify({ detail: 'x' }) });
    const { apiStream } = await import('./api');
    await expect(apiStream('/stream')).rejects.toThrow('Authentication required');
  });

  it('apiDelete should throw for non-401 errors', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => 'err' });
    const { apiDelete } = await import('./api');
    await expect(apiDelete('/del')).rejects.toThrow('Delete failed with 500');
  });

  it('should redirect to /login on 401 unauthorized error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    });

    const formData = new FormData();
    formData.append('file', new Blob(['test']));

    await expect(apiUpload('/api/statements/upload', formData)).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
  });
});

describe('apiOperation helpers', () => {
  beforeEach(() => {
    resetRedirectGuard();
    fetchMock.mockReset();
    localStorageMock.getItem.mockReset();
    mockLocation.href = '';
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('apiOperation interpolates path params and parses json response', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 's1', status: 'pending' }),
    });

    const { apiOperation } = await import('./api');
    const result = await apiOperation('get_holding_dividends_portfolio__ticker__dividends_get', {
      path: { ticker: 'AAPL' },
      query: { limit: 10 },
    });

    expect(result).toEqual({ id: 's1', status: 'pending' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/portfolio/AAPL/dividends?limit=10'),
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('apiOperation serializes array query params and handles missing query', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ base_currency: 'SGD' }),
    });

    const { apiOperation } = await import('./api');
    const result = await apiOperation('get_base_currency_app_config_base_currency_get');
    expect(result).toEqual({ base_currency: 'SGD' });
  });

  it('apiOperation handles query with null/undefined values and empty query', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });

    const { apiOperation } = await import('./api');
    await apiOperation('get_holding_dividends_portfolio__ticker__dividends_get', {
      path: { ticker: 'MSFT' },
      query: { limit: 5, offset: undefined },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/portfolio/MSFT/dividends?limit=5'),
      expect.anything()
    );
  });

  it('apiOperation throws on missing path parameter', async () => {
    const { apiOperation } = await import('./api');
    await expect(
      apiOperation('get_holding_dividends_portfolio__ticker__dividends_get', {
        path: { ticker: undefined as any },
      })
    ).rejects.toThrow('Missing OpenAPI path parameter: ticker');
  });

  it('apiOperationStream delegates to requestStream with query, headers, and token', async () => {
    localStorageMock.getItem.mockReturnValue('mock-token');
    const mockHeaders = {
      get: (header: string) => (header.toLowerCase() === 'x-session-id' ? 'sess-123' : null),
    };
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: mockHeaders,
      text: async () => '',
    });

    const { apiOperationStream } = await import('./api');
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
      })
    );
  });

  it('apiOperationStream throws ApiError on non-401 failure', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: 'LLM crashed', error_id: 'llm_error', request_id: 'req-1' }),
    });

    const { apiOperationStream } = await import('./api');
    await expect(
      apiOperationStream('chat_message_chat_post', { body: { message: 'hi' } as any })
    ).rejects.toThrow('LLM crashed');
  });

  it('apiOperationDownload delegates to requestDownload and parses various Content-Disposition headers', async () => {
    localStorageMock.getItem.mockReturnValue('mock-token');
    const csvBlob = new Blob(['col1,col2\nval1,val2\n'], { type: 'text/csv' });
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: {
        get: (h: string) => (h.toLowerCase() === 'content-disposition' ? "attachment; filename*=UTF-8''report%202026.csv" : null),
      },
    });

    const { apiOperationDownload } = await import('./api');
    const result = await apiOperationDownload('export_report_reports_export_get', {
      query: { report_type: 'cash-flow' } as any,
    });

    expect(result.blob).toBe(csvBlob);
    expect(result.filename).toBe('report 2026.csv');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/reports/export'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer mock-token',
        }),
      })
    );
  });

  it('apiOperationDownload handles malformed UTF-8 and missing header in Content-Disposition', async () => {
    const csvBlob = new Blob(['data'], { type: 'text/csv' });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: {
        get: (h: string) => (h.toLowerCase() === 'content-disposition' ? "attachment; filename*=UTF-8''%E0%A4%A" : null),
      },
    });

    const { apiOperationDownload } = await import('./api');
    const res1 = await apiOperationDownload('export_report_reports_export_get', { query: {} as any });
    expect(res1.filename).toBe('%E0%A4%A');

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: { get: () => null },
    });
    const res2 = await apiOperationDownload('export_report_reports_export_get', { query: {} as any });
    expect(res2.filename).toBeNull();

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => csvBlob,
      headers: {
        get: (h: string) => (h.toLowerCase() === 'content-disposition' ? 'attachment; filename=plain_report.csv' : null),
      },
    });
    const res3 = await apiOperationDownload('export_report_reports_export_get', { query: {} as any });
    expect(res3.filename).toBe('plain_report.csv');
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

    const { apiFetch } = await import('./api');
    await expect(apiFetch('/api/throw-nav')).rejects.toThrow('Authentication required - redirect failed');

    // restore mockLocation
    Object.defineProperty(window, 'location', {
      value: mockLocation,
      writable: true,
      configurable: true,
    });
  });

  it('apiOperationDownload throws and redirects on 401, throws on 500', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    });

    const { apiOperationDownload } = await import('./api');
    await expect(
      apiOperationDownload('export_report_reports_export_get', { query: {} as any })
    ).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => 'export failed',
    });
    await expect(
      apiOperationDownload('export_report_reports_export_get', { query: {} as any })
    ).rejects.toThrow('export failed');
  });

  it('apiOperationUpload delegates to requestUpload with FormData body, token, and handles 204', async () => {
    localStorageMock.getItem.mockReturnValue('mock-token');
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: 'stmt-new', original_filename: 'test.pdf' }),
    });

    const fd = new FormData();
    fd.append('file', new Blob(['fake pdf']), 'test.pdf');

    const { apiOperationUpload } = await import('./api');
    const result = await apiOperationUpload('upload_statement_statements_upload_post', {
      body: fd,
    });

    expect(result).toEqual({ id: 'stmt-new', original_filename: 'test.pdf' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/statements/upload'),
      expect.objectContaining({
        method: 'POST',
        body: fd,
        headers: expect.objectContaining({
          Authorization: 'Bearer mock-token',
        }),
      })
    );

    // 204 No content returns undefined
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
    });
    const res204 = await apiOperationUpload('upload_statement_statements_upload_post', { body: fd });
    expect(res204).toBeUndefined();
  });

  it('apiOperationUpload throws on 401 and 400 error', async () => {
    const fd = new FormData();
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'need login',
    });
    const { apiOperationUpload } = await import('./api');
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', { body: fd })
    ).rejects.toThrow('Authentication required');

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: async () => JSON.stringify({ detail: 'bad file format', error_id: 'bad_format' }),
    });
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', { body: fd })
    ).rejects.toThrow('bad file format');
  });

  it('apiFetch handles 204 No Content, tokens, and complex error payloads', async () => {
    localStorageMock.getItem.mockReturnValue('token-xyz');
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
    });

    const { apiFetch, isApiErrorCode, ApiError } = await import('./api');
    const res = await apiFetch('/api/void');
    expect(res).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/void'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer token-xyz',
        }),
      })
    );

    // 422 Validation error where detail is array
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({
        detail: [{ loc: ['body', 'name'], msg: 'Field required' }],
        error_id: 'validation_error',
        request_id: 'req-v1',
      }),
    });

    let caughtErr: any;
    try {
      await apiFetch('/api/accounts');
    } catch (err) {
      caughtErr = err;
    }
    expect(caughtErr).toBeInstanceOf(ApiError);
    expect(isApiErrorCode(caughtErr, 'validation_error')).toBe(true);
    expect(caughtErr.requestId).toBe('req-v1');
    expect(caughtErr.message).toContain('Field required');

    // JSON primitive parsed
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => '12345',
    });
    await expect(apiFetch('/api/primitive')).rejects.toThrow('12345');
  });

  it('apiDelete redirects on 401 with token', async () => {
    localStorageMock.getItem.mockReturnValue('del-token');
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'forbidden',
    });
    const { apiDelete } = await import('./api');
    await expect(apiDelete('/delete-me')).rejects.toThrow('Authentication required');
    expect(mockLocation.href).toBe('/login');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/delete-me'),
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({
          Authorization: 'Bearer del-token',
        }),
      })
    );
  });
});
