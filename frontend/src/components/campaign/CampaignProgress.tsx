import type { Campaign } from '../../api/client';
import { campaignStatus } from '../../lib/campaign';

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
  const st = campaignStatus(c.status);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`font-bold uppercase ${st.tone}`}>{st.label}</span>
        <span className="text-muted">
          {c.sent} enviados · {c.pending} pendientes · {c.failed} fallidos
        </span>
      </div>
      <div
        role="progressbar"
        aria-label="Avance de la campaña"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-2 overflow-hidden rounded-full bg-panel-2"
      >
        <div className="h-full rounded-full bg-green" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted">
        Hoy: {c.sent_today} de {c.daily_cap} · 1 DM cada {c.delay_min}–{c.delay_max} seg · de{' '}
        {c.hour_start} a {c.hour_end} h (hora argentina)
      </p>
      {c.status === 'blocked' && (
        <div className="rounded-lg border border-yellow/50 bg-yellow/10 px-3 py-2 text-xs text-yellow">
          <p className="font-semibold">⚠ Instagram frenó los envíos de DMs</p>
          {c.error && <p className="mt-1 opacity-90">{c.error}</p>}
          <p className="mt-1 font-medium">
            No reanudes hasta que pase el bloqueo (suele durar 12 a 48 h). Probar antes lo alarga.
          </p>
        </div>
      )}
      {c.status === 'paused' && c.error && (
        // Paused by the sender itself (session down, IP block, Instagram asked to
        // slow down): the reason, so it is fixed before resuming.
        <div className="rounded-lg border border-yellow/50 bg-yellow/10 px-3 py-2 text-xs text-yellow">
          <p className="font-semibold">⏸ La app pausó la campaña para cuidar la cuenta</p>
          <p className="mt-1 opacity-90">{c.error}</p>
          <p className="mt-1 font-medium">
            Revisá la conexión con Instagram (chip IG arriba a la derecha) y reanudá cuando esté
            resuelto.
          </p>
        </div>
      )}
      {c.status === 'paused' && !c.error && (
        <p className="text-xs text-muted">La pausaste vos. Reanudala cuando quieras.</p>
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
        La campaña sigue sola mientras la app esté abierta en tu compu (no cierres la ventana donde
        corre). Podés cerrar este cuadro.
      </p>
    </div>
  );
}
