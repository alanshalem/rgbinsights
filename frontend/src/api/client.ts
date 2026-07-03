// Thin fetch wrapper. All request/response shapes come from ./generated
// (produced by `npm run gen:api` from the backend OpenAPI) — no hand-written
// response types, so the client is type-safe end to end.
import type { paths } from './generated';

const BASE = '/api';

export type TrafficLight = 'red' | 'yellow' | 'green';

export type UserOut =
  paths['/users']['get']['responses']['200']['content']['application/json'][number];
export type PostOut =
  paths['/posts']['get']['responses']['200']['content']['application/json'][number];
export type ScanResult =
  paths['/scan/post']['post']['responses']['200']['content']['application/json'];
export type ScanBatchResult =
  paths['/scan/posts']['post']['responses']['200']['content']['application/json'];
export type SyncResult =
  paths['/sync/dms']['post']['responses']['200']['content']['application/json'];
export type Health = paths['/health']['get']['responses']['200']['content']['application/json'];

type ApiErrorDetail = { code: string; message: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** Instagram asked for verification — the UI surfaces this specially. */
  get isChallenge(): boolean {
    return this.code === 'challenge_required' || this.code === 'login_required';
  }
}

function isErrorDetail(v: unknown): v is ApiErrorDetail {
  return typeof v === 'object' && v !== null && 'code' in v && 'message' in v;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    if (isErrorDetail(detail)) throw new ApiError(res.status, detail.code, detail.message);
    throw new ApiError(res.status, 'unknown', `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export type UsersQuery = {
  post?: string;
  status?: TrafficLight;
  search?: string;
  order?: 'username' | 'status';
};

export const api = {
  health: () => request<Health>('/health'),

  listUsers: (q: UsersQuery = {}) => {
    const params = new URLSearchParams();
    if (q.post) params.set('post', q.post);
    if (q.status) params.set('status', q.status);
    if (q.search) params.set('search', q.search);
    if (q.order) params.set('order', q.order);
    const qs = params.toString();
    return request<UserOut[]>(`/users${qs ? `?${qs}` : ''}`);
  },

  listPosts: () => request<PostOut[]>('/posts'),

  scanPost: (url: string) =>
    request<ScanResult>('/scan/post', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  scanPosts: (urls: string[]) =>
    request<ScanBatchResult>('/scan/posts', {
      method: 'POST',
      body: JSON.stringify({ urls }),
    }),

  syncDms: () => request<SyncResult>('/sync/dms', { method: 'POST' }),
};
