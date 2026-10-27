import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

function makeFetchMock(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
    headers: {
      get: (name: string) => headers[name] ?? null,
    },
  });
}

describe('apiOperation', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-http-client.1
  it('AC16.10.1 returns JSON on 200 response', async () => {
    const fetchMock = makeFetchMock(200, { id: 1, name: 'test' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    const result = await apiOperation('get_me_auth_me_get');

    expect(result).toEqual({ id: 1, name: 'test' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/me'),
      expect.objectContaining({ credentials: 'include', headers: expect.any(Object) })
    );
  });

  // AC-meta.fe-http-client.2
  it('AC16.10.2 returns undefined on 204 No Content', async () => {
    const fetchMock = makeFetchMock(204, null);
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    const result = await apiOperation('delete_account_accounts__account_id__delete', {
      path: { account_id: 'test' },
    });

    expect(result).toBeUndefined();
  });

  // AC-meta.fe-http-client.3
  it('AC16.10.3 throws with detail message on JSON error response', async () => {
    const fetchMock = makeFetchMock(400, { detail: 'Validation failed' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await expect(apiOperation('get_me_auth_me_get')).rejects.toThrow('Validation failed');
  });

  // AC-meta.fe-http-client.4
  it('AC16.10.4 throws with raw text on non-JSON error response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Internal Server Error'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await expect(apiOperation('get_me_auth_me_get')).rejects.toThrow('Internal Server Error');
  });

  // AC-meta.fe-http-client.5
  it('AC16.10.5 redirects to /login on 401 unauthorized response', async () => {
    const fetchMock = makeFetchMock(401, { detail: 'Not authenticated' });
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('window', { location: { href: '' } });

    const { apiOperation, resetRedirectGuard } = await import('../lib/api');
    resetRedirectGuard();
    await expect(apiOperation('list_statements_statements_get')).rejects.toThrow('Authentication required');
    expect(window.location.href).toBe('/login');
  });

  // AC-meta.fe-http-client.13
  it('AC16.10.13 normalizes path without leading slash', async () => {
    const fetchMock = makeFetchMock(200, {});
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await apiOperation('get_base_currency_app_config_base_currency_get');

    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toMatch(/\/api\/app-config\/base-currency/);
  });

  // AC-identity.fe-auth2.1
  it('AC1.10.3 sends HttpOnly auth cookies by default', async () => {
    const fetchMock = makeFetchMock(200, {});
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await apiOperation('get_me_auth_me_get');

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ credentials: 'include' }));
    const calledHeaders = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(calledHeaders.Authorization).toBeUndefined();
  });

  it('test_AC8_13_48 uses raw text when apiFetch error JSON is not an object', async () => {
    const fetchMock = makeFetchMock(422, 'false');
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await expect(apiOperation('get_me_auth_me_get')).rejects.toThrow('false');
  });

  it('test_AC8_13_48 reports redirect assignment failures', async () => {
    const fetchMock = makeFetchMock(401, {});
    vi.stubGlobal('fetch', fetchMock);
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('window', {
      location: {
        get href() {
          return '';
        },
        set href(_: string) {
          throw new Error('navigation blocked');
        },
      },
    });

    const { apiOperation, resetRedirectGuard } = await import('../lib/api');
    resetRedirectGuard();

    await expect(apiOperation('list_statements_statements_get')).rejects.toThrow('Authentication required - redirect failed');
    expect(consoleSpy).toHaveBeenCalledWith('[api] Failed to redirect to login:', expect.any(Error));
    consoleSpy.mockRestore();
  });
});

describe('resetRedirectGuard', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-http-client.6
  it('AC16.10.6 resetRedirectGuard is exported and callable', async () => {
    const { resetRedirectGuard } = await import('../lib/api');
    expect(() => resetRedirectGuard()).not.toThrow();
  });
});

describe('apiDelete', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-http-client.7
  it('AC16.10.7 succeeds on 200 response', async () => {
    const fetchMock = makeFetchMock(200, { success: true });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await expect(
      apiOperation('delete_account_accounts__account_id__delete', {
        path: { account_id: '1' },
      }),
    ).resolves.toBeDefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/accounts/1'),
      expect.objectContaining({ credentials: 'include', method: 'DELETE' })
    );
  });

  // AC-meta.fe-http-client.8
  it('AC16.10.8 throws on non-ok response', async () => {
    const fetchMock = makeFetchMock(404, '');
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api');
    await expect(
      apiOperation('delete_account_accounts__account_id__delete', {
        path: { account_id: 'missing' },
      }),
    ).rejects.toThrow('Request failed with 404');
  });

  // AC-meta.fe-http-client.15
  it('AC16.10.15 handles 401 redirect in apiDelete', async () => {
    const fetchMock = makeFetchMock(401, {});
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('window', { location: { href: '' } });

    const { apiOperation, resetRedirectGuard } = await import('../lib/api');
    resetRedirectGuard();
    await expect(
      apiOperation('delete_account_accounts__account_id__delete', {
        path: { account_id: 'delete-unauth' },
      }),
    ).rejects.toThrow('Authentication required');
    expect(window.location.href).toBe('/login');
  });
});


describe('apiOperationStream', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-http-client.9
  it('AC16.10.9 returns response and sessionId on success', async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      text: () => Promise.resolve(''),
      json: () => Promise.resolve({}),
      headers: { get: (name: string) => name === 'X-Session-Id' ? 'sess-abc' : null },
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse));

    const { apiOperationStream } = await import('../lib/api');
    const result = await apiOperationStream('chat_message_chat_post', {
      body: { message: 'hello' } as any,
    });

    expect(result.response).toBe(mockResponse);
    expect(result.sessionId).toBe('sess-abc');
  });

  // AC-meta.fe-http-client.10
  it('AC16.10.10 throws on non-ok response', async () => {
    const fetchMock = makeFetchMock(503, { detail: 'Service Unavailable' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationStream } = await import('../lib/api');
    await expect(
      apiOperationStream('chat_message_chat_post', {
        body: { message: 'hello' } as any,
      }),
    ).rejects.toThrow('Service Unavailable');
  });

  it('test_AC8_13_48 handles non-object and invalid JSON stream errors', async () => {
    const { apiOperationStream } = await import('../lib/api');

    vi.stubGlobal('fetch', makeFetchMock(429, 'false'));
    await expect(
      apiOperationStream('chat_message_chat_post', {
        body: { message: 'hello' } as any,
      }),
    ).rejects.toThrow('false');

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('{bad json'),
    }));
    await expect(
      apiOperationStream('chat_message_chat_post', {
        body: { message: 'hello' } as any,
      }),
    ).rejects.toThrow('{bad json');
  });
});

describe('apiOperationUpload', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-http-client.11
  it('AC16.10.11 returns JSON on 200 response', async () => {
    const fetchMock = makeFetchMock(200, { uploaded: true });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationUpload } = await import('../lib/api');
    const fd = new FormData();
    fd.append('file', new Blob(['data']), 'test.pdf');

    const result = await apiOperationUpload('upload_statement_statements_upload_post', {
      body: fd,
    });
    expect(result).toEqual({ uploaded: true });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/statements/upload'),
      expect.objectContaining({ credentials: 'include', method: 'POST', body: fd })
    );
  });

  // AC-meta.fe-http-client.12
  it('AC16.10.12 returns undefined on 204 No Content', async () => {
    const fetchMock = makeFetchMock(204, null);
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationUpload } = await import('../lib/api');
    const fd = new FormData();
    const result = await apiOperationUpload('upload_statement_statements_upload_post', {
      body: fd,
    });
    expect(result).toBeUndefined();
  });

  // AC-meta.fe-http-client.17
  it('AC16.10.17 handles 401 redirect in apiUpload', async () => {
    const fetchMock = makeFetchMock(401, {});
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('window', { location: { href: '' } });

    const { apiOperationUpload, resetRedirectGuard } = await import('../lib/api');
    resetRedirectGuard();
    const fd = new FormData();
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', {
        body: fd,
      }),
    ).rejects.toThrow('Authentication required');
    expect(window.location.href).toBe('/login');
  });

  // AC-meta.fe-http-client.18
  it('AC16.10.18 throws with detail message on JSON error response', async () => {
    const fetchMock = makeFetchMock(400, { detail: 'Upload limit exceeded' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationUpload } = await import('../lib/api');
    const fd = new FormData();
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', {
        body: fd,
      }),
    ).rejects.toThrow('Upload limit exceeded');
  });

  // AC-meta.fe-http-client.19
  it('AC16.10.19 throws with raw text on non-JSON error response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Server Crash'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationUpload } = await import('../lib/api');
    const fd = new FormData();
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', {
        body: fd,
      }),
    ).rejects.toThrow('Server Crash');
  });

  it('test_AC8_13_48 uses raw text when apiUpload error JSON is not an object', async () => {
    const fetchMock = makeFetchMock(413, 'false');
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationUpload } = await import('../lib/api');
    const fd = new FormData();
    await expect(
      apiOperationUpload('upload_statement_statements_upload_post', {
        body: fd,
      }),
    ).rejects.toThrow('false');
  });
});

describe('user settings & session bootstrap client (EPIC-022 AC22.15 / #1010)', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-ia-nav.19
  it('AC22.15.1 get_current_user_settings_users_me_settings_get GETs /api/users/me/settings', async () => {
    const fetchMock = makeFetchMock(200, {
      enable_ai_reconciliation: true,
      enable_ai_classification: false,
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api-client');
    const result = await apiOperation('get_current_user_settings_users_me_settings_get');

    expect(result).toEqual({ enable_ai_reconciliation: true, enable_ai_classification: false });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/users\/me\/settings/);
    expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET');
  });

  it('AC22.15.1 patch_current_user_settings_users_me_settings_patch PATCHes the edited flags', async () => {
    const fetchMock = makeFetchMock(200, {
      enable_ai_reconciliation: false,
      enable_ai_classification: true,
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api-client');
    const result = await apiOperation('patch_current_user_settings_users_me_settings_patch', {
      body: { enable_ai_classification: true },
    });

    expect(result).toEqual({ enable_ai_reconciliation: false, enable_ai_classification: true });
    const [calledUrl, calledInit] = fetchMock.mock.calls[0];
    expect(calledUrl).toMatch(/\/api\/users\/me\/settings/);
    expect(calledInit.method).toBe('PATCH');
    expect(JSON.parse(calledInit.body as string)).toEqual({ enable_ai_classification: true });
  });

  it('AC22.15.1 patch_current_user_settings_users_me_settings_patch surfaces backend error detail', async () => {
    const fetchMock = makeFetchMock(400, { detail: 'Invalid setting' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api-client');
    await expect(
      apiOperation('patch_current_user_settings_users_me_settings_patch', {
        body: { enable_ai_reconciliation: true },
      }),
    ).rejects.toThrow('Invalid setting');
  });

  it('AC22.15.3 get_me_auth_me_get GETs /api/auth/me', async () => {
    const fetchMock = makeFetchMock(200, {
      id: 'user-1',
      email: 'a@example.com',
      name: null,
      created_at: '2026-01-01T00:00:00Z',
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api-client');
    const result = await apiOperation('get_me_auth_me_get');

    expect(result.email).toBe('a@example.com');
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/auth\/me/);
  });
});

describe('apiOperationDownload', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // AC-meta.fe-http-client.21
  it('AC5.17.1 downloads authenticated CSV blobs and preserves the server filename', async () => {
    const csvBlob = new Blob(['section,account,amount\nAssets,Cash,100.00\n'], { type: 'text/csv' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(csvBlob),
      text: () => Promise.resolve(''),
      headers: {
        get: (name: string) =>
          name.toLowerCase() === 'content-disposition'
            ? 'attachment; filename="cash-flow-2026-01-01-to-2026-01-31.csv"'
            : null,
      },
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationDownload } = await import('../lib/api');
    const result = await apiOperationDownload('export_report_reports_export_get', {
      query: { report_type: 'cash-flow' } as any,
    });

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ credentials: 'include' }));
    expect(result.blob).toBe(csvBlob);
    expect(result.filename).toBe('cash-flow-2026-01-01-to-2026-01-31.csv');
  });

  it('test_AC8_13_48 parses UTF-8 and malformed download filenames', async () => {
    const csvBlob = new Blob(['ok'], { type: 'text/csv' });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(csvBlob),
        headers: {
          get: () => "attachment; filename*=UTF-8''cash-flow-%E2%82%AC.csv",
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(csvBlob),
        headers: {
          get: () => "attachment; filename*=UTF-8''%E0%A4%A",
        },
      });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperationDownload } = await import('../lib/api');
    await expect(
      apiOperationDownload('export_report_reports_export_get', {
        query: {} as any,
      }),
    ).resolves.toMatchObject({
      blob: csvBlob,
      filename: 'cash-flow-€.csv',
    });
    await expect(
      apiOperationDownload('export_report_reports_export_get', {
        query: {} as any,
      }),
    ).resolves.toMatchObject({
      blob: csvBlob,
      filename: '%E0%A4%A',
    });
  });

  it('test_AC8_13_48 reports download failures and redirects on 401', async () => {
    const { apiOperationDownload, resetRedirectGuard } = await import('../lib/api');

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve(''),
    }));
    await expect(
      apiOperationDownload('export_report_reports_export_get', {
        query: {} as any,
      }),
    ).rejects.toMatchObject({ name: 'ApiError', status: 503, message: 'Request failed with 503' });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    }));
    vi.stubGlobal('window', { location: { href: '' } });
    resetRedirectGuard();

    await expect(
      apiOperationDownload('export_report_reports_export_get', {
        query: {} as any,
      }),
    ).rejects.toThrow('Authentication required');
    expect(window.location.href).toBe('/login');
  });
});

describe('base currency app-config api (EPIC-012 AC12.39)', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('AC12.39 get_base_currency_app_config_base_currency_get GETs the effective base currency', async () => {
    const fetchMock = makeFetchMock(200, { base_currency: 'SGD' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api-client');
    const result = await apiOperation('get_base_currency_app_config_base_currency_get');

    expect(result).toEqual({ base_currency: 'SGD' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/app-config/base-currency'),
      expect.objectContaining({ credentials: 'include' })
    );
  });

  it('AC12.39 update_base_currency_app_config_base_currency_put PUTs the new ISO code', async () => {
    const fetchMock = makeFetchMock(200, { base_currency: 'USD' });
    vi.stubGlobal('fetch', fetchMock);

    const { apiOperation } = await import('../lib/api-client');
    const result = await apiOperation('update_base_currency_app_config_base_currency_put', {
      body: { base_currency: 'USD' },
    });

    expect(result).toEqual({ base_currency: 'USD' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/app-config/base-currency'),
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ base_currency: 'USD' }) })
    );
  });
});
