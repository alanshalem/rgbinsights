import { useEffect, useId, useRef, useState } from 'react';
import { ApiError, toApiError } from '../api/client';
import {
  isJobKind,
  useEnrichEvent,
  useRefreshEvent,
  useRunningJob,
  useStatus,
  useSyncDms,
} from '../api/hooks';
import { JOB_META } from '../lib/jobs';
import { fmtAgo } from '../lib/time';

const NEEDS_FIESTA = 'Elegí una fiesta arriba';

/** One menu entry. Module-level so it keeps its identity across renders (no
 * remount of every item each time the menu re-renders). */
function Item({
  label,
  hint,
  freshness,
  disabled,
  onClick,
}: {
  label: string;
  hint: string;
  freshness?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-panel-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
    >
      <span className="text-sm font-medium">{label}</span>
      <span className={`text-xs ${disabled ? 'text-yellow' : 'text-muted'}`}>
        {disabled ? NEEDS_FIESTA : hint}
      </span>
      {freshness && !disabled && (
        <span className="mono text-xs text-muted">Última vez: {freshness}</span>
      )}
    </button>
  );
}

/** "Actualizar ▾": one menu for the three refresh depths (DMs / posts + DMs /
 * quién te sigue). Each item shows how fresh its data is; "Traer todo de cero"
 * ignores what was already read, for when something looks wrong. */
export function ActionsMenu({
  event,
  lastScannedAt,
  primary,
  onError,
}: {
  event?: number;
  lastScannedAt?: string | null;
  /** The main next step right now: drawn filled + glowing, else outlined. */
  primary: boolean;
  onError: (e: ApiError | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [force, setForce] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const status = useStatus();
  const sync = useSyncDms();
  const refresh = useRefreshEvent();
  const enrich = useEnrichEvent();
  // One Instagram job at a time (the backend refuses a second): also busy while
  // a job started elsewhere (scan bar, posts drawer, another tab) runs.
  const running = useRunningJob();
  const mine = { sync, refresh, enrich } as const;
  // Until the job shows up in the task list, the pending mutation tells the kind.
  const pendingKind = (Object.keys(mine) as (keyof typeof mine)[]).find((k) => mine[k].isPending);
  const busyKind = running?.kind ?? pendingKind;
  const busy = busyKind !== undefined;
  const busyLabel = busyKind && isJobKind(busyKind) ? JOB_META[busyKind].busy : 'Actualizando…';

  // A job started elsewhere closes the menu (its entries can't run meanwhile).
  useEffect(() => {
    if (busy) setOpen(false);
  }, [busy]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const run = <T,>(m: { mutate: (arg: T, opts?: object) => void }, arg: T) => {
    onError(null);
    setOpen(false);
    m.mutate(arg, { onError: (e: unknown) => onError(toApiError(e)) });
  };

  const look = primary
    ? 'bg-blue text-bg shadow-[0_0_24px_-6px_var(--color-blue)] hover:opacity-90'
    : 'border border-blue/60 text-blue hover:bg-blue/10';

  return (
    <div className="relative" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={busy}
        aria-expanded={open}
        aria-controls={menuId}
        className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition-opacity disabled:opacity-60 ${look}`}
      >
        {busy ? `↻ ${busyLabel}` : '↻ Actualizar ▾'}
      </button>
      {open && (
        <div
          id={menuId}
          className="absolute z-20 mt-1 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-border bg-panel shadow-xl"
        >
          <Item
            label={JOB_META.sync.title}
            hint="Actualiza los colores del semáforo (rápido)"
            freshness={fmtAgo(status.data?.dms_synced_at)}
            onClick={() => run(sync, { force, event })}
          />
          <Item
            label={JOB_META.refresh.title}
            hint="Likes y comentarios nuevos de sus posts + DMs"
            freshness={fmtAgo(lastScannedAt)}
            disabled={event === undefined}
            onClick={() => event !== undefined && run(refresh, { id: event, force })}
          />
          <Item
            label={JOB_META.enrich.title}
            hint="Lento: marca quién te sigue y cuántos seguidores tiene cada uno"
            freshness={fmtAgo(status.data?.relationships_synced_at)}
            disabled={event === undefined}
            onClick={() => event !== undefined && run(enrich, { id: event, force })}
          />
          <label className="flex items-start gap-2 border-t border-border px-3 py-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <b className="text-ink">Traer todo de cero</b> (más lento y más pedidos a Instagram;
              usalo solo si algo quedó mal). Si no, la app reusa lo que leyó hace poco para cuidar
              la cuenta.
            </span>
          </label>
        </div>
      )}
    </div>
  );
}
