import { useActivity } from '../api/hooks';

const KIND_LABEL: Record<string, string> = {
  scan: 'Escaneo',
  sync: 'Sync DMs',
  refresh: 'Actualización',
  enrich: 'Enriquecer',
  campaign: 'Campaña',
};

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function ActivityPage({ onBack }: { onBack: () => void }) {
  const activity = useActivity();
  const rows = activity.data ?? [];

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="display text-2xl font-black tracking-tight uppercase">Actividad</h1>
        <button
          onClick={onBack}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-sm hover:bg-[var(--color-panel)]"
        >
          ← Volver al panel
        </button>
      </div>
      <p className="mb-4 text-sm text-[var(--color-muted)]">
        Historial de lo que corrió (escaneos, syncs, enriquecidos, campañas) y si anduvo.
      </p>

      {rows.length === 0 ? (
        <p className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] py-12 text-center text-sm text-[var(--color-muted)]">
          Sin actividad todavía.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((a) => (
            <li
              key={a.id}
              className="flex items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-2.5 text-sm"
            >
              <span
                className={
                  a.status === 'error' ? 'text-[var(--color-red)]' : 'text-[var(--color-green)]'
                }
              >
                {a.status === 'error' ? '✕' : '✓'}
              </span>
              <span className="mono w-28 shrink-0 text-xs text-[var(--color-muted)]">
                {KIND_LABEL[a.kind] ?? a.kind}
              </span>
              <span className="min-w-0 flex-1 truncate">{a.message}</span>
              <span className="mono shrink-0 text-xs text-[var(--color-muted)]">
                {fmtTime(a.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
