import { usePosts, useRescanEvent, useRunningJob } from '../api/hooks';
import { ApiError, toApiError } from '../api/client';
import { JOB_META } from '../lib/jobs';
import { fmtAgo } from '../lib/time';
import { JobBusyNote } from './ui/JobBusyNote';

export function PostsDrawer({
  event,
  onError,
}: {
  event?: number;
  onError: (e: ApiError | null) => void;
}) {
  const posts = usePosts(event);
  const rescan = useRescanEvent();
  const igBusy = useRunningJob() !== undefined; // one Instagram job at a time
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
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">
          Posts {event === undefined ? '(todas las fiestas)' : 'de la fiesta'} · {rows.length}
        </h3>
        {event !== undefined && (
          <div className="flex flex-col items-end gap-0.5">
            <button
              type="button"
              onClick={handleRescan}
              disabled={rescan.isPending || igBusy || rows.length === 0}
              className="rounded-lg bg-panel-2 px-3 py-1 text-xs font-medium hover:bg-border disabled:opacity-40"
            >
              {rescan.isPending ? JOB_META.rescan.busy : `↻ ${JOB_META.rescan.title}`}
            </button>
            <span className="text-xs text-muted">
              Likes y comentarios nuevos, sin DMs (para todo: Actualizar ▾)
            </span>
          </div>
        )}
      </div>
      {igBusy && !rescan.isPending && event !== undefined && rows.length > 0 && (
        <div className="mb-2">
          <JobBusyNote />
        </div>
      )}
      {rows.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted">
          Todavía no hay posts. Pegá sus links arriba y tocá <b>Escanear</b>.
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
                {p.caption.slice(0, 60) || 'sin texto'}
              </a>
              <span className="shrink-0 text-xs text-muted">
                escaneado {fmtAgo(p.last_scanned_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {rescan.data && (
        <p className="mt-2 text-xs text-muted">
          Listo: {String(rescan.data.result.usuarios ?? 0)} personas (
          {String(rescan.data.result.nuevos ?? 0)} nuevas).
        </p>
      )}
    </div>
  );
}
