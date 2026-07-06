import type { Campaign } from '../../api/client';

export function CampaignProgress({
  c,
  onStop,
  onResume,
  busy,
}: {
  c: Campaign;
  onStop: () => void;
  onResume: () => void;
  busy: boolean;
}) {
  const done = c.sent + c.failed;
  const pct = c.total ? Math.round((done / c.total) * 100) : 0;
  const badge: Record<string, string> = {
    running: 'text-green',
    paused: 'text-yellow',
    blocked: 'text-red',
    done: 'text-muted',
  };
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex items-center gap-2">
        <span className={`mono font-bold uppercase ${badge[c.status]}`}>{c.status}</span>
        <span className="mono text-muted">
          {c.sent} enviados · {c.pending} pendientes · {c.failed} fallidos
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-panel-2">
        <div className="h-full rounded-full bg-green" style={{ width: `${pct}%` }} />
      </div>
      <p className="mono text-xs text-muted">
        hoy {c.sent_today}/{c.daily_cap} · 1 cada {c.delay_min}-{c.delay_max}s · {c.hour_start}-
        {c.hour_end}h
      </p>
      {c.status === 'blocked' && (
        <p className="rounded-lg border border-red/50 bg-red/10 px-3 py-2 text-xs text-red">
          Instagram frenó el envío: {c.error}. Esperá un rato (horas), y si querés reanudá.
        </p>
      )}
      <div className="flex gap-2">
        {c.status === 'running' ? (
          <button
            type="button"
            onClick={onStop}
            disabled={busy}
            className="rounded-lg border border-border px-4 py-2 font-semibold disabled:opacity-40"
          >
            Pausar
          </button>
        ) : (
          <button
            type="button"
            onClick={onResume}
            disabled={busy || c.pending === 0}
            className="rounded-lg bg-green px-4 py-2 font-semibold text-bg disabled:opacity-40"
          >
            Reanudar
          </button>
        )}
      </div>
      <p className="text-xs text-muted">
        La campaña sigue en segundo plano mientras el backend esté corriendo. Podés cerrar esta
        ventana.
      </p>
    </div>
  );
}
