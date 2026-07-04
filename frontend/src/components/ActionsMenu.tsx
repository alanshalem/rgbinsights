import { useEffect, useRef, useState } from 'react';
import { ApiError, toApiError } from '../api/client';
import { useEnrichEvent, useRefreshEvent, useStatus, useSyncDms } from '../api/hooks';

/** "hace 2h" / "hace 5min" / "recién" / "nunca" from an ISO timestamp. */
function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return 'nunca';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'recién';
  if (mins < 60) return `hace ${mins}min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `hace ${hours}h`;
  return `hace ${Math.floor(hours / 24)}d`;
}

/** "Actualizar ▾": one menu for the three refresh depths (DMs / posts+DMs /
 * relación+perfiles). Each item shows how fresh its data is; "forzar" ignores
 * the cache when you really want to re-fetch. */
export function ActionsMenu({
  event,
  lastScannedAt,
  onError,
}: {
  event?: number;
  lastScannedAt?: string | null;
  onError: (e: ApiError | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [force, setForce] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const status = useStatus();
  const sync = useSyncDms();
  const refresh = useRefreshEvent();
  const enrich = useEnrichEvent();
  const busy = sync.isPending || refresh.isPending || enrich.isPending;

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const run = <T,>(m: { mutate: (arg: T, opts?: object) => void }, arg: T) => {
    onError(null);
    setOpen(false);
    m.mutate(arg, { onError: (e: unknown) => onError(toApiError(e)) });
  };

  const Item = ({
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
  }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-[var(--color-panel-2)] disabled:opacity-40"
    >
      <span className="flex items-center justify-between gap-4 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-xs text-[var(--color-muted)]">{hint}</span>
      </span>
      {freshness && (
        <span className="mono text-[10px] text-[var(--color-muted)]">actualizado {freshness}</span>
      )}
    </button>
  );

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={busy}
        className="rounded-lg bg-[var(--color-blue)] px-3 py-1.5 text-sm font-semibold text-[var(--color-bg)] shadow-[0_0_24px_-6px_var(--color-blue)] transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {busy ? '↻ Actualizando…' : '↻ Actualizar ▾'}
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-72 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] shadow-xl">
          <Item
            label="Sincronizar DMs"
            hint="rápido"
            freshness={fmtAgo(status.data?.dms_synced_at)}
            onClick={() => run(sync, force)}
          />
          <Item
            label="Actualizar fiesta"
            hint="posts + DMs"
            freshness={`posts ${fmtAgo(lastScannedAt)}`}
            disabled={event === undefined}
            onClick={() => event !== undefined && run(refresh, { id: event, force })}
          />
          <Item
            label="Relación + perfiles"
            hint="lento · te sigue, seguidores"
            freshness={`relación ${fmtAgo(status.data?.relationships_synced_at)}`}
            disabled={event === undefined}
            onClick={() => event !== undefined && run(enrich, { id: event, force })}
          />
          <label className="flex items-center gap-2 border-t border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-muted)]">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            <span>
              Forzar (ignorar caché) — más lento, más pedidos a IG.{' '}
              <span className="text-[var(--color-muted)]">
                Normalmente reusa lo reciente para evitar bloqueos.
              </span>
            </span>
          </label>
        </div>
      )}
    </div>
  );
}
