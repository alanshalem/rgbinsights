import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type UsersQuery } from './client';

export function useUsers(query: UsersQuery) {
  return useQuery({
    queryKey: ['users', query],
    queryFn: () => api.listUsers(query),
  });
}

export function usePosts() {
  return useQuery({ queryKey: ['posts'], queryFn: () => api.listPosts() });
}

/** Invalidate the derived views after any write so counts/columns refresh. */
function useRefreshAfter() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ['users'] });
    void qc.invalidateQueries({ queryKey: ['posts'] });
  };
}

export function useScanPosts() {
  const refresh = useRefreshAfter();
  return useMutation({
    mutationFn: (urls: string[]) => api.scanPosts(urls),
    onSuccess: refresh,
  });
}

export function useSyncDms() {
  const refresh = useRefreshAfter();
  return useMutation({
    mutationFn: () => api.syncDms(),
    onSuccess: refresh,
  });
}
