import { useEffect, useRef, useState } from 'react';
import { ApiError, toApiError } from '../api/client';
import { useEnrichEvent, useRefreshEvent, useSyncDms } from '../api/hooks';

/** "Actualizar ▾": one menu for the three refresh depths (DMs / posts+DMs /
 * relación+perfiles), instead of separate loose buttons. */
export function ActionsMenu({
  event,
  onError,
}: {
  event?: number;
  onError: (e: ApiError | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
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
    disabled,
    onClick,
  }: {
    label: string;
    hint: string;
    disabled?: boolean;
    onClick: () => void;
  }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center justify-between gap-4 px-3 py-2 text-left text-sm hover:bg-[var(--color-panel-2)] disabled:opacity-40"
    >
      <span className="font-medium">{label}</span>
      <span className="text-xs text-[var(--color-muted)]">{hint}</span>
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
        <div className="absolute z-20 mt-1 w-64 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] shadow-xl">
          <Item
            label="Sincronizar DMs"
            hint="rápido"
            onClick={() => run(sync, undefined as void)}
          />
          <Item
            label="Actualizar fiesta"
            hint="posts + DMs"
            disabled={event === undefined}
            onClick={() => event !== undefined && run(refresh, event)}
          />
          <Item
            label="Relación + perfiles"
            hint="lento · te sigue, seguidores"
            disabled={event === undefined}
            onClick={() => event !== undefined && run(enrich, event)}
          />
        </div>
      )}
    </div>
  );
}
