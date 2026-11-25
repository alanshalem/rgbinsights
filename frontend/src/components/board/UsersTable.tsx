import { useEffect, useState } from 'react';
import type { Order, TrafficLight } from '../../api/client';
import { useUsers } from '../../api/hooks';
import type { ActiveFilters } from '../../lib/filters';
import { summarize } from '../../lib/user';
import { Avatar } from '../ui/Avatar';
import { PostLink } from '../ui/PostLink';
import { TrafficChip, TrafficLegend } from '../ui/TrafficChip';
import { NoResults } from './NoResults';

const PAGE = 50;

type TableQuery = {
  event?: number;
  status?: TrafficLight;
  search?: string;
  order: Order;
  follows?: boolean;
};

export function UsersTable({
  query,
  total,
  filters,
  onClearFilters,
}: {
  query: TableQuery;
  total: number;
  filters: ActiveFilters;
  onClearFilters: () => void;
}) {
  const [page, setPage] = useState(0);
  // Reset to first page whenever the filters change (every field of the query).
  useEffect(
    () => setPage(0),
    [query.event, query.status, query.search, query.order, query.follows]
  );

  const pages = Math.max(1, Math.ceil(total / PAGE));
  // The list can also shrink under us (a sync moves people to another color):
  // never ask for, or show, a page past the last one.
  const current = Math.min(page, pages - 1);
  const users = useUsers({ ...query, limit: PAGE, offset: current * PAGE });
  const rows = users.data ?? [];

  if (total === 0) return <NoResults filters={filters} onClear={onClearFilters} />;

  return (
    <div className="flex flex-col gap-3">
      <TrafficLegend />
      <div className="overflow-x-auto rounded-2xl border border-border bg-panel">
        <table className="w-full min-w-[680px] text-left text-sm">
          <thead className="border-b border-border text-xs text-muted">
            <tr>
              <th className="px-4 py-3 font-medium">Usuario</th>
              <th className="px-4 py-3 font-medium">Estado</th>
              <th className="px-4 py-3 font-medium" title="Con cuántos posts interactuó">
                Posts
              </th>
              <th className="px-4 py-3 font-medium">Interacción</th>
              <th className="px-4 py-3 font-medium">Comentario</th>
              <th className="px-4 py-3 font-medium">Acción</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => {
              const { commented, liked, commentPreview, commentUrl, likeUrl } = summarize(u);
              return (
                <tr key={u.pk} className="border-b border-border/50 last:border-0">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <Avatar user={u} size={32} />
                      <div className="min-w-0">
                        <div className="truncate font-medium">@{u.username}</div>
                        <div className="truncate text-xs text-muted">{u.full_name}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <TrafficChip light={u.traffic_light} />
                  </td>
                  <td className="px-4 py-3 text-muted">{u.engagement_count}</td>
                  <td className="px-4 py-3 text-muted">
                    <span className="flex flex-wrap items-center gap-x-1.5">
                      {commented && (
                        <PostLink
                          url={commentUrl}
                          title="Abrir el comentario en Instagram"
                          className="hover:text-ink hover:underline"
                        >
                          comentó
                        </PostLink>
                      )}
                      {commented && liked && <span>·</span>}
                      {liked && (
                        <PostLink
                          url={likeUrl}
                          title="Abrir el post que likeó"
                          className="hover:text-ink hover:underline"
                        >
                          likeó
                        </PostLink>
                      )}
                      {!commented && !liked && '—'}
                    </span>
                  </td>
                  <td className="max-w-[240px] px-4 py-3 text-muted">
                    <PostLink
                      url={commentUrl}
                      title="Abrir el comentario en Instagram"
                      className="line-clamp-1 hover:text-ink hover:underline"
                    >
                      {commentPreview ?? '—'}
                    </PostLink>
                  </td>
                  <td className="px-4 py-3">
                    <a
                      href={u.action_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-ink hover:underline"
                    >
                      {u.thread_id !== null ? 'Abrir DM' : 'Ver perfil'}
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            type="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
            className="rounded-lg border border-border px-3 py-1 disabled:opacity-40"
          >
            ← Anterior
          </button>
          <span className="text-muted">
            Página {current + 1} de {pages}
          </span>
          <button
            type="button"
            disabled={current + 1 >= pages}
            onClick={() => setPage(current + 1)}
            className="rounded-lg border border-border px-3 py-1 disabled:opacity-40"
          >
            Siguiente →
          </button>
        </div>
      )}
    </div>
  );
}
