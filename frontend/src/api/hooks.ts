import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { api, type EventCreate, type UsersQuery } from './client';

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

const ALL_VIEWS: readonly ViewKey[] = ['users', 'counts', 'posts', 'events', 'status'];

/** What each write changes on the backend → the only views worth refetching.
 * Keys match the backend task kinds (`/tasks`) plus the untracked writes. */
const CHANGES: Record<string, readonly ViewKey[]> = {
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

/** Refetch only the views a write of `kind` changed (unknown kind → all of them). */
export function invalidateAfter(qc: QueryClient, kind: string) {
  for (const key of CHANGES[kind] ?? ALL_VIEWS) void qc.invalidateQueries({ queryKey: [key] });
}

function useInvalidateAfter(kind: string) {
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

export function useScanPosts() {
  const refresh = useInvalidateAfter('scan');
  return useMutation({
    mutationFn: ({ urls, eventId }: { urls: string[]; eventId?: number }) =>
      api.scanPosts(urls, eventId),
    onSuccess: refresh,
  });
}

export function useRescanEvent() {
  const refresh = useInvalidateAfter('rescan');
  return useMutation({
    mutationFn: (eventId: number) => api.rescanEvent(eventId),
    onSuccess: refresh,
  });
}

type Forceable = { id: number; force?: boolean };

export function useEnrichEvent() {
  const refresh = useInvalidateAfter('enrich');
  return useMutation({
    mutationFn: ({ id, force }: Forceable) => api.enrichEvent(id, force),
    onSuccess: refresh,
  });
}

/** Re-scan the fiesta's posts + sync DMs in one call. */
export function useRefreshEvent() {
  const refresh = useInvalidateAfter('refresh');
  return useMutation({
    mutationFn: ({ id, force }: Forceable) => api.refreshEvent(id, force),
    onSuccess: refresh,
  });
}

export function useSyncDms() {
  const refresh = useInvalidateAfter('sync');
  return useMutation({
    mutationFn: (arg: { force?: boolean; event?: number } = {}) =>
      api.syncDms(arg.force, arg.event),
    onSuccess: refresh,
  });
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

/** Poll only while something is happening: a mutation in flight (`active`) or a
 * task already running. Idle → no polling (one fetch on mount). */
export function useTasks(active: boolean) {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(),
    refetchInterval: (q) =>
      active || (q.state.data?.some((t) => t.status === 'running') ?? false) ? 1200 : false,
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
