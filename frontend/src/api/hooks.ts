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

export function useCounts(query: Pick<UsersQuery, 'event' | 'post' | 'search'>) {
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
