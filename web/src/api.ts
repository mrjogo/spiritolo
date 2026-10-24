// The one HTTP client for the Spiritolo API. Same-origin, cookie-authenticated
// (the passkey session cookie is HttpOnly, so nothing here touches tokens).
// In dev, Vite proxies /api to the FastAPI process (see vite.config.ts).

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export interface ApiInit {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}

export async function api<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? (init.body !== undefined ? 'POST' : 'GET'),
    headers: init.body !== undefined ? { 'content-type': 'application/json' } : undefined,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: 'same-origin',
    signal: init.signal,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const json = await res.json();
      detail = (json && typeof json === 'object' && 'detail' in json) ? (json as { detail: unknown }).detail : json;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- The generic allowlisted table read (POST /api/ops/query) -------------

export type FilterOp = 'eq' | 'neq' | 'in' | 'lt' | 'lte' | 'gt' | 'gte' | 'ilike' | 'like' | 'is';

export interface QueryFilter {
  col: string;
  op: FilterOp;
  value: unknown;
}

export interface QueryOrder {
  col: string;
  asc?: boolean;
}

export interface QuerySpec {
  table: string;
  select?: string;
  filters?: QueryFilter[];
  /** Every term must match at least one of `cols` (LIKE %term%). */
  search?: { terms: string[]; cols: string[] };
  order?: QueryOrder | QueryOrder[];
  limit?: number;
  offset?: number;
}

export interface Page<T> {
  rows: T[];
  total: number;
}

export function queryTable<T>(spec: QuerySpec): Promise<Page<T>> {
  return api<Page<T>>('/api/ops/query', { body: spec });
}

/** First matching row or null (the `.maybeSingle()` of old). */
export async function queryOne<T>(table: string, filters: QueryFilter[], select = '*'): Promise<T | null> {
  const { rows } = await queryTable<T>({ table, select, filters, limit: 1 });
  return rows[0] ?? null;
}

/** Every matching row, up to the server cap. */
export async function queryAll<T>(
  table: string,
  opts: { filters?: QueryFilter[]; order?: QueryOrder | QueryOrder[]; select?: string } = {},
): Promise<T[]> {
  const { rows } = await queryTable<T>({ table, select: opts.select ?? '*', filters: opts.filters, order: opts.order, limit: 1000 });
  return rows;
}
