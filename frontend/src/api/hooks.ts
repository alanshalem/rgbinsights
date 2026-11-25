import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { api, ApiError, type EventCreate, type Task, type UsersQuery } from './client';
import { notify } from '../lib/notices';

export function useEvents() {
  return useQuery({ queryKey: ['events'], queryFn: () => api.listEvents() });
}

export function useUsers(query: UsersQuery) {
  return useQuery({
    queryKey: ['users', query],
    queryFn: () => api.listUsers(query),
  });
}

/** Board column: users in pages of `pageSize`. "Cargar más" (`fetchNextPage`)
 * asks only for the next page (`offset` = rows already loaded) and appends it.
 * Filters are part of the key, so a new search/filter/order starts at page 1. */
export function useUserPages(query: Omit<UsersQuery, 'limit' | 'offset'>, pageSize: number) {
  return useInfiniteQuery({
    queryKey: ['users', 'pages', pageSize, query],
    queryFn: ({ pageParam }) => api.listUsers({ ...query, limit: pageSize, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length < pageSize ? undefined : pages.reduce((n, p) => n + p.length, 0),
  });
}

export function useCounts(query: Pick<UsersQuery, 'event' | 'post' | 'search' | 'follows'>) {
  return useQuery({
    queryKey: ['counts', query],
    queryFn: () => api.counts(query),
  });
}

export function usePosts(event?: number) {
  return useQuery({ queryKey: ['posts', event ?? null], queryFn: () => api.listPosts(event) });
}

type ViewKey = 'users' | 'counts' | 'posts' | 'events' | 'status';

export const ALL_VIEWS: readonly ViewKey[] = ['users', 'counts', 'posts', 'events', 'status'];

/** The background job kinds (`Task.kind` from /tasks). */
export type JobKind = 'scan' | 'rescan' | 'enrich' | 'sync' | 'refresh';
/** Every write that changes views: the jobs plus the untracked writes. */
export type ChangeKind = JobKind | 'event';

/** What each write changes on the backend → the only views worth refetching. */
const CHANGES: Record<ChangeKind, readonly ViewKey[]> = {
  // POST /events: a new, empty fiesta row (no posts/users yet).
  event: ['events'],
  // Posts + engagements + users; the fiesta's posts_count / last_scanned_at.
  scan: ['users', 'counts', 'posts', 'events'],
  rescan: ['users', 'counts', 'posts', 'events'],
  // Profiles + follows_us (the counts' "te siguen" filter) + relationships_synced_at.
  enrich: ['users', 'counts', 'status'],
  // DM threads → traffic lights + dms_synced_at.
  sync: ['users', 'counts', 'status'],
  // rescan + sync.
  refresh: ALL_VIEWS,
};

/** Narrow a backend task kind (a plain string) to a kind this build knows. */
export function isJobKind(kind: string): kind is JobKind {
  return kind !== 'event' && Object.hasOwn(CHANGES, kind);
}

export function invalidateViews(qc: QueryClient, views: readonly ViewKey[]) {
  for (const key of views) void qc.invalidateQueries({ queryKey: [key] });
}

/** Refetch only the views a write of `kind` changed. */
export function invalidateAfter(qc: QueryClient, kind: ChangeKind) {
  invalidateViews(qc, CHANGES[kind]);
}

/** After a job ends. The backend's task kind is a plain string: a kind this
 * build knows refreshes only what it changed; an unknown one (explicit
 * fallback) refreshes every view. Local reads only (no Instagram request). */
export function refreshAfterJob(qc: QueryClient, kind: string) {
  if (isJobKind(kind)) invalidateAfter(qc, kind);
  else invalidateViews(qc, ALL_VIEWS);
}

function useInvalidateAfter(kind: ChangeKind) {
  const qc = useQueryClient();
  return () => invalidateAfter(qc, kind);
}

/** Freshness of the shared data (last relationships/DMs sync), for the hints. */
export function useStatus() {
  return useQuery({ queryKey: ['status'], queryFn: () => api.getStatus() });
}

/** Instagram session health for the connection chip + reconnect banner. */
export function useIgStatus() {
  return useQuery({
    queryKey: ['ig-status'],
    queryFn: () => api.igStatus(),
    refetchInterval: 20000,
    refetchIntervalInBackground: false, // paused while the tab is hidden
  });
}

export function useCreateEvent() {
  const refresh = useInvalidateAfter('event');
  return useMutation({
    mutationFn: (body: EventCreate) => api.createEvent(body),
    onSuccess: refresh,
  });
}

// -- background jobs (S16) ---------------------------------------------------

const LOST_JOB = 'Se perdió el seguimiento de la tarea (¿se reinició el backend?).';
const UNKNOWN_OUTCOME = 'La tarea terminó mientras no estabas mirando — se actualizaron los datos.';
/** Waits before retrying GET /tasks/{id} after a network error; then give up. */
const RETRY_MS = [1000, 2000, 4000, 8000];

/** Settle when the job ends, watching the live ['tasks'] list (SSE, or polling
 * as the fallback): resolve with the finished task, reject with its error as an
 * ApiError (so onError and the challenge banner work as with a plain request).
 * A list without the job (stale, or it was pruned 25 s after ending) is checked
 * against GET /tasks/{id}:
 *  - still running → keep waiting (the mutation stays pending);
 *  - 404 (pruned, or the backend restarted) → the outcome is unknown, not an
 *    error: refresh the views that kind changes, show a neutral notice and
 *    resolve with `null`;
 *  - a network error → retry with backoff (RETRY_MS), then give up (LOST_JOB).
 * Reads our backend's memory only: never an Instagram request. */
function waitForJob(qc: QueryClient, job: Task): Promise<Task | null> {
  // Show it right away (the toast), before the stream's next snapshot.
  qc.setQueryData<Task[]>(['tasks'], (old = []) =>
    old.some((t) => t.id === job.id) ? old : [...old, job]
  );
  return new Promise((resolve, reject) => {
    let settled = false;
    let checking = false; // a GET /tasks/{id}, or the wait before its retry
    let failures = 0; // consecutive network errors of that GET
    let retry: ReturnType<typeof setTimeout> | undefined;
    const settle = () => {
      settled = true;
      clearTimeout(retry);
      unsubscribe();
    };
    const finish = (t: Task) => {
      settle();
      if (t.status === 'done') resolve(t);
      else reject(new ApiError(0, t.error_code ?? 'unknown', t.error ?? 'La tarea falló.'));
    };
    const lost = () => {
      settle();
      refreshAfterJob(qc, job.kind);
      notify(job.kind, UNKNOWN_OUTCOME);
      resolve(null);
    };
    const check = () => {
      if (settled) return;
      const t = qc.getQueryData<Task[]>(['tasks'])?.find((x) => x.id === job.id);
      if (t) {
        if (t.status !== 'running') finish(t);
        return;
      }
      if (checking) return;
      checking = true;
      api.getTask(job.id).then(
        (fresh) => {
          checking = false;
          failures = 0;
          if (!settled && fresh.status !== 'running') finish(fresh);
        },
        (e: unknown) => {
          if (settled) return;
          if (e instanceof ApiError && e.status === 404) return lost();
          if (failures >= RETRY_MS.length) {
            settle();
            return reject(new ApiError(0, 'unknown', LOST_JOB));
          }
          // The list may bring the job meanwhile (check settles it from there).
          retry = setTimeout(() => {
            checking = false;
            check();
          }, RETRY_MS[failures++]);
        }
      );
    };
    const unsubscribe = qc.getQueryCache().subscribe((e) => {
      if (e.query.queryKey[0] === 'tasks') check();
    });
    check();
  });
}

/** A background job: the POST answers 202 + the job at once, and the mutation
 * stays pending until the job ends, so `isPending` and `onError` keep their
 * meaning; `data` is the finished task, or `null` when its outcome could not
 * be followed (see waitForJob). The Toasts refresh the views it changed when
 * its "done" arrives (CHANGES), for every tab, so no onSuccess invalidation. */
function useJob<A>(start: (arg: A) => Promise<Task>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async (arg: A) => waitForJob(qc, await start(arg)) });
}

export function useScanPosts() {
  return useJob(({ urls, eventId }: { urls: string[]; eventId?: number }) =>
    api.scanPosts(urls, eventId)
  );
}

export function useRescanEvent() {
  return useJob((eventId: number) => api.rescanEvent(eventId));
}

type Forceable = { id: number; force?: boolean };

export function useEnrichEvent() {
  return useJob(({ id, force }: Forceable) => api.enrichEvent(id, force));
}

/** Re-scan the fiesta's posts + sync DMs in one job. */
export function useRefreshEvent() {
  return useJob(({ id, force }: Forceable) => api.refreshEvent(id, force));
}

export function useSyncDms() {
  return useJob((arg: { force?: boolean; event?: number } = {}) =>
    api.syncDms(arg.force, arg.event)
  );
}

/** The Instagram job running now, if any: every job talks to Instagram, so the
 * backend runs one at a time (409 for another) and the UI disables the rest.
 * Reads the ['tasks'] cache kept live by the Toasts (useTaskStream + useTasks)
 * through a plain cache subscription: no query observer, so no fetch of its own
 * and no options merged into that query. */
export function useRunningJob(): Task | undefined {
  const qc = useQueryClient();
  const subscribe = useCallback(
    (onChange: () => void) => qc.getQueryCache().subscribe(onChange),
    [qc]
  );
  const tasks = useSyncExternalStore(subscribe, () => qc.getQueryData<Task[]>(['tasks']));
  return tasks?.find((t) => t.status === 'running');
}

// -- campaigns -------------------------------------------------------------

export function usePresets() {
  return useQuery({ queryKey: ['presets'], queryFn: () => api.listPresets(), staleTime: Infinity });
}

export function useCampaign(eventId?: number) {
  return useQuery({
    queryKey: ['campaign', eventId ?? null],
    queryFn: () => api.getCampaign(eventId as number),
    enabled: eventId !== undefined,
    // Poll while a campaign is actively sending.
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 4000 : false),
  });
}

export function useStopCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.stopCampaign(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['campaign'] }),
  });
}

export function useResumeCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.resumeCampaign(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['campaign'] }),
  });
}

// -- toasts (live task/campaign progress) ----------------------------------

/** Live task list pushed by the server (SSE, GET /tasks/stream) into the
 * ['tasks'] cache. Returns whether the stream is connected: while it is not
 * (connecting, the browser retrying, no EventSource), useTasks polls instead.
 * Reads memory on the backend only: never triggers an Instagram request. */
export function useTaskStream(): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (typeof EventSource === 'undefined') return;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const open = () => {
      const es = new EventSource(api.tasksStreamUrl);
      source = es;
      es.onopen = () => setConnected(true);
      es.addEventListener('tasks', (e) => {
        qc.setQueryData<Task[]>(['tasks'], JSON.parse((e as MessageEvent<string>).data));
        setConnected(true);
      });
      es.onerror = () => {
        setConnected(false); // poll meanwhile; the browser retries on its own…
        if (es.readyState === EventSource.CLOSED) {
          // …unless it gave up (e.g. an HTTP error): try again later ourselves.
          es.close();
          retry = setTimeout(open, 30000);
        }
      };
    };
    open();
    return () => {
      clearTimeout(retry);
      source?.close();
    };
  }, [qc]);
  return connected;
}

/** Polling fallback of the stream: only while it is down AND something is
 * happening (a mutation in flight = `active`, or a task already running).
 * Streaming or idle → no polling (one fetch on mount). */
export function useTasks(active: boolean, streaming: boolean) {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(),
    refetchInterval: (q) =>
      !streaming && (active || (q.state.data?.some((t) => t.status === 'running') ?? false))
        ? 1200
        : false,
  });
}

export function useActiveCampaign(active: boolean) {
  return useQuery({
    queryKey: ['activeCampaign'],
    queryFn: () => api.activeCampaign(),
    refetchInterval: (q) => (active || q.state.data?.status === 'running' ? 4000 : false),
  });
}

/** Polls only while the Activity page is mounted (its sole observer) and the
 * tab is visible. */
export function useActivity() {
  return useQuery({
    queryKey: ['activity'],
    queryFn: () => api.listActivity(),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
}

/** Danger zone: wipe all data, then refresh every view. */
export function useResetAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (confirm: string) => api.resetAll(confirm),
    onSuccess: () => void qc.invalidateQueries(),
  });
}
