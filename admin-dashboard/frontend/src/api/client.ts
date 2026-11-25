export interface ApiOptions {
  bg?: boolean;
}

export async function api<T = any>(
  url: string,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' = 'GET',
  body: Record<string, any> | null = null,
  opts: ApiOptions = {}
): Promise<T & { error?: string }> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (opts.bg) {
    headers['X-Background-Poll'] = '1';
  }
  const init: RequestInit = {
    method,
    headers,
    credentials: 'same-origin',
  };
  if (body !== null) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(url, init);
    if (res.redirected && res.url.includes('/login')) {
      return { error: 'Unauthorized' } as T & { error?: string };
    }
    if (!res.ok && res.status >= 500) {
      return { error: `Server error ${res.status}` } as T & { error?: string };
    }
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      return { error: `Unexpected response (${res.status})` } as T & { error?: string };
    }
    return (await res.json()) as T & { error?: string };
  } catch (err: any) {
    return { error: err?.message || 'Network error' } as T & { error?: string };
  }
}
