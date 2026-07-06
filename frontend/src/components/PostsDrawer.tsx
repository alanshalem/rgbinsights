import { usePosts, useRescanEvent } from '../api/hooks';
import { ApiError, toApiError } from '../api/client';

function timeAgo(iso: string | null): string {
  if (!iso) return 'nunca';
  const ms = Date.now() - new Date(iso).getTime();
  const days = Math.floor(ms / 86_400_000);
  if (days > 0) return `hace ${days}d`;
  const hours = Math.floor(ms / 3_600_000);
  if (hours > 0) return `hace ${hours}h`;
  return 'recién';
}

export function PostsDrawer({
  event,
  onError,
}: {
  event?: number;
  onError: (e: ApiError | null) => void;
}) {
  const posts = usePosts(event);
  const rescan = useRescanEvent();
  const rows = posts.data ?? [];

  const handleRescan = () => {
    if (event === undefined) return;
    onError(null);
    rescan.mutate(event, {
      onError: (e) => onError(toApiError(e)),
    });
  };

  return (
    <div className="rounded-2xl border border-border bg-panel p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          Posts {event === undefined ? '(todos)' : 'de la fiesta'} · {rows.length}
        </h3>
        {event !== undefined && (
          <button
            type="button"
            onClick={handleRescan}
            disabled={rescan.isPending || rows.length === 0}
            className="rounded-lg bg-panel-2 px-3 py-1 text-xs font-medium hover:bg-border disabled:opacity-40"
          >
            {rescan.isPending ? 'Re-escaneando…' : '↻ Re-escanear fiesta'}
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted">
          Sin posts. Escaneá URLs {event !== undefined && 'con esta fiesta seleccionada'}.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((p) => (
            <li
              key={p.media_pk}
              className="flex items-center justify-between gap-2 rounded-lg bg-bg px-3 py-2 text-sm"
            >
              <a
                href={p.url}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 flex-1 truncate hover:underline"
              >
                <span className="text-muted">/{p.shortcode}</span>{' '}
                {p.caption.slice(0, 60) || 'sin caption'}
              </a>
              <span className="shrink-0 text-xs text-muted">{timeAgo(p.last_scanned_at)}</span>
            </li>
          ))}
        </ul>
      )}
      {rescan.isSuccess && (
        <p className="mt-2 text-xs text-muted">
          Re-escaneado: {rescan.data.total_users_found} usuarios ({rescan.data.total_new_users}{' '}
          nuevos).
        </p>
      )}
    </div>
  );
}
