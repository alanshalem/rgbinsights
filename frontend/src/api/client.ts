// Thin fetch wrapper. All request/response shapes come from ./generated
// (produced by `npm run gen:api` from the backend OpenAPI) — type-safe end to end.
import type { paths } from './generated';

const BASE = '/api';

export type TrafficLight = 'red' | 'yellow' | 'green';
export type Order = 'status' | 'username' | 'fans' | 'followers';

export type UserOut =
  paths['/users']['get']['responses']['200']['content']['application/json'][number];
export type PostOut =
  paths['/posts']['get']['responses']['200']['content']['application/json'][number];
export type EventOut =
  paths['/events']['get']['responses']['200']['content']['application/json'][number];
export type StatusCounts =
  paths['/users/counts']['get']['responses']['200']['content']['application/json'];
export type ScanBatchResult =
  paths['/scan/posts']['post']['responses']['200']['content']['application/json'];
export type SyncResult =
  paths['/sync/dms']['post']['responses']['200']['content']['application/json'];
export type EventCreate = paths['/events']['post']['requestBody']['content']['application/json'];
export type EventRefresh =
  paths['/events/{event_id}/refresh']['post']['responses']['200']['content']['application/json'];
export type Preset =
  paths['/campaigns/presets']['get']['responses']['200']['content']['application/json'][number];
export type CampaignPreview =
  paths['/events/{event_id}/campaign/preview']['post']['responses']['200']['content']['application/json'];
export type Campaign =
  paths['/events/{event_id}/campaign']['post']['responses']['200']['content']['application/json'];
export type CampaignCreate =
  paths['/events/{event_id}/campaign']['post']['requestBody']['content']['application/json'];
export type MessageSample =
  paths['/events/{event_id}/campaign/test']['post']['responses']['200']['content']['application/json'];
export type Task =
  paths['/tasks']['get']['responses']['200']['content']['application/json'][number];
export type Activity =
  paths['/activity']['get']['responses']['200']['content']['application/json'][number];

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

/** Normalize any thrown value into an ApiError for the UI. */
export function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, 'unknown', String(e));
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
  event?: number;
  post?: string;
  status?: TrafficLight;
  search?: string;
  order?: Order;
  follows?: boolean;
  limit?: number;
  offset?: number;
};

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const api = {
  listUsers: (q: UsersQuery = {}) => request<UserOut[]>(`/users${qs({ ...q })}`),

  counts: (q: Pick<UsersQuery, 'event' | 'post' | 'search'> = {}) =>
    request<StatusCounts>(`/users/counts${qs({ ...q })}`),

  listPosts: (event?: number) => request<PostOut[]>(`/posts${qs({ event })}`),

  listEvents: () => request<EventOut[]>('/events'),

  createEvent: (body: EventCreate) =>
    request<EventOut>('/events', { method: 'POST', body: JSON.stringify(body) }),

  rescanEvent: (eventId: number) =>
    request<ScanBatchResult>(`/events/${eventId}/rescan`, { method: 'POST' }),

  enrichEvent: (eventId: number) =>
    request<{ enriched: number }>(`/events/${eventId}/enrich`, { method: 'POST' }),

  refreshEvent: (eventId: number) =>
    request<EventRefresh>(`/events/${eventId}/refresh`, { method: 'POST' }),

  scanPosts: (urls: string[], eventId?: number) =>
    request<ScanBatchResult>('/scan/posts', {
      method: 'POST',
      body: JSON.stringify({ urls, event_id: eventId ?? null }),
    }),

  syncDms: () => request<SyncResult>('/sync/dms', { method: 'POST' }),

  listPresets: () => request<Preset[]>('/campaigns/presets'),

  previewCampaign: (eventId: number, body: CampaignCreate) =>
    request<CampaignPreview>(`/events/${eventId}/campaign/preview`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  testCampaign: (eventId: number, body: CampaignCreate, username?: string) =>
    request<MessageSample>(`/events/${eventId}/campaign/test${qs({ username })}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createCampaign: (eventId: number, body: CampaignCreate) =>
    request<Campaign>(`/events/${eventId}/campaign`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getCampaign: (eventId: number) => request<Campaign | null>(`/events/${eventId}/campaign`),

  stopCampaign: (id: number) => request<Campaign>(`/campaigns/${id}/stop`, { method: 'POST' }),

  resumeCampaign: (id: number) => request<Campaign>(`/campaigns/${id}/resume`, { method: 'POST' }),

  listTasks: () => request<Task[]>('/tasks'),

  activeCampaign: () => request<Campaign | null>('/campaigns/active'),

  listActivity: () => request<Activity[]>('/activity'),

  resetAll: (confirm: string) =>
    request<{ deleted: Record<string, number> }>('/reset', {
      method: 'POST',
      body: JSON.stringify({ confirm }),
    }),
};
