// Thin fetch wrapper. All request/response shapes come from ./generated
// (produced by `npm run gen:api` from the backend OpenAPI) — type-safe end to end.
import type { paths } from './generated';

export const BASE = '/api';

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
export type EventCreate = paths['/events']['post']['requestBody']['content']['application/json'];
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
/** A background job (scan/rescan/sync/refresh/enrich): what its POST answers
 * (202) and what /tasks and /tasks/stream report while it runs and after. */
export type Task =
  paths['/tasks']['get']['responses']['200']['content']['application/json'][number];
export type Activity =
  paths['/activity']['get']['responses']['200']['content']['application/json'][number];
export type Status = paths['/status']['get']['responses']['200']['content']['application/json'];
export type IgStatus =
  paths['/ig/status']['get']['responses']['200']['content']['application/json'];

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

/** The ApiError for a failed response, from its JSON `detail` when present. */
async function errorFrom(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = (await res.json()).detail;
  } catch {
    /* non-JSON error body */
  }
  if (isErrorDetail(detail)) return new ApiError(res.status, detail.code, detail.message);
  // A bare string detail (e.g. FastAPI's 500 "Internal Server Error") is still
  // more useful than "HTTP 500" — surface it instead of the raw status.
  if (typeof detail === 'string' && detail.trim())
    return new ApiError(res.status, 'unknown', detail);
  return new ApiError(res.status, 'unknown', `HTTP ${res.status}`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw await errorFrom(res);
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

export type ExportFormat = 'xlsx' | 'pdf';

/** What the screen shows: the /users filters (all rows, no paging) and, for the
 * Board, `by_status` = one block per color like its three columns. */
export type ExportQuery = Omit<UsersQuery, 'limit' | 'offset'> & { by_status?: boolean };

function filenameFrom(res: Response, fallback: string): string {
  const m = /filename="?([^";]+)"?/i.exec(res.headers.get('Content-Disposition') ?? '');
  return m?.[1] ?? fallback;
}

/** Download the on-screen list as Excel/PDF (built from the local DB only). */
async function downloadExport(format: ExportFormat, q: ExportQuery): Promise<void> {
  const res = await fetch(`${BASE}/users/export${qs({ ...q, format })}`);
  if (!res.ok) throw await errorFrom(res);
  const url = URL.createObjectURL(await res.blob());
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filenameFrom(res, `semaforo.${format}`);
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Let the click start the download before the blob URL goes away.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

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

  exportUsers: downloadExport,

  listPosts: (event?: number) => request<PostOut[]>(`/posts${qs({ event })}`),

  listEvents: () => request<EventOut[]>('/events'),

  createEvent: (body: EventCreate) =>
    request<EventOut>('/events', { method: 'POST', body: JSON.stringify(body) }),

  // The long Instagram operations start a background job and answer at once
  // (202 + the job); its progress and result arrive on /tasks/stream.
  rescanEvent: (eventId: number) => request<Task>(`/events/${eventId}/rescan`, { method: 'POST' }),

  enrichEvent: (eventId: number, force = false) =>
    request<Task>(`/events/${eventId}/enrich${qs({ force })}`, { method: 'POST' }),

  refreshEvent: (eventId: number, force = false) =>
    request<Task>(`/events/${eventId}/refresh${qs({ force })}`, { method: 'POST' }),

  scanPosts: (urls: string[], eventId?: number) =>
    request<Task>('/scan/posts', {
      method: 'POST',
      body: JSON.stringify({ urls, event_id: eventId ?? null }),
    }),

  syncDms: (force = false, event?: number) =>
    request<Task>(`/sync/dms${qs({ force, event })}`, { method: 'POST' }),

  getStatus: () => request<Status>('/status'),

  igStatus: () => request<IgStatus>('/ig/status'),
  igReauth: () => request<IgStatus>('/ig/reauth', { method: 'POST' }),
  igDisconnect: () => request<IgStatus>('/ig/disconnect', { method: 'POST' }),
  igSetSessionid: (sessionid: string) =>
    request<IgStatus>('/ig/sessionid', { method: 'POST', body: JSON.stringify({ sessionid }) }),

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

  getTask: (id: string) => request<Task>(`/tasks/${id}`),

  /** Server-Sent Events: `tasks` events carrying the same list as listTasks(). */
  tasksStreamUrl: `${BASE}/tasks/stream`,

  activeCampaign: () => request<Campaign | null>('/campaigns/active'),

  listActivity: () => request<Activity[]>('/activity'),

  resetAll: (confirm: string) =>
    request<{ deleted: Record<string, number> }>('/reset', {
      method: 'POST',
      body: JSON.stringify({ confirm }),
    }),
};
