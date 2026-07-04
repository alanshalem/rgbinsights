import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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

export function useCounts(query: Pick<UsersQuery, 'event' | 'post' | 'search' | 'follows'>) {
  return useQuery({
    queryKey: ['counts', query],
    queryFn: () => api.counts(query),
  });
}

export function usePosts(event?: number) {
  return useQuery({ queryKey: ['posts', event ?? null], queryFn: () => api.listPosts(event) });
}

/** Invalidate every derived view after a write so counts/columns refresh. */
function useRefreshAll() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ['users'] });
    void qc.invalidateQueries({ queryKey: ['counts'] });
    void qc.invalidateQueries({ queryKey: ['posts'] });
    void qc.invalidateQueries({ queryKey: ['events'] });
  };
}

export function useCreateEvent() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (body: EventCreate) => api.createEvent(body),
    onSuccess: refresh,
  });
}

export function useScanPosts() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ urls, eventId }: { urls: string[]; eventId?: number }) =>
      api.scanPosts(urls, eventId),
    onSuccess: refresh,
  });
}

export function useRescanEvent() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (eventId: number) => api.rescanEvent(eventId),
    onSuccess: refresh,
  });
}

export function useEnrichEvent() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (eventId: number) => api.enrichEvent(eventId),
    onSuccess: refresh,
  });
}

/** Re-scan the fiesta's posts + sync DMs in one call. */
export function useRefreshEvent() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: (eventId: number) => api.refreshEvent(eventId),
    onSuccess: refresh,
  });
}

export function useSyncDms() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: () => api.syncDms(),
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

export function useActivity() {
  return useQuery({
    queryKey: ['activity'],
    queryFn: () => api.listActivity(),
    refetchInterval: 5000,
  });
}
