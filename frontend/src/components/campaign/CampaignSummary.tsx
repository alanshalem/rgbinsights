import type { CampaignPreview } from '../../api/client';
import { fmtGap } from '../../lib/campaign';
import type { Params } from './types';

/** Risk note + the "se enviarán N" card (count, ETA, follower split, samples). */
export function CampaignSummary({
  preview,
  params,
  recalc,
  recalcBusy,
}: {
  preview: CampaignPreview | null;
  params: Params;
  recalc: () => void;
  recalcBusy: boolean;
}) {
  return (
    <>
      <div className="rounded-xl border border-red/40 bg-red/10 px-3 py-2 text-xs text-red">
        <b>Riesgo:</b> el envío masivo es lo más riesgoso de Instagram (action-block / ban). Se
        frena solo si IG avisa — empezá con <b>Óptimo</b> o Máxima cautela.
      </div>

      {/* summary card — big count, ETA, and the follower / non-follower split */}
      <div className="rounded-xl border border-border bg-bg p-4">
        {preview ? (
          <>
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                Se enviarán
              </span>
              <button
                type="button"
                onClick={recalc}
                disabled={recalcBusy}
                className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-panel disabled:opacity-40"
              >
                {recalcBusy ? '…' : 'Recalcular'}
              </button>
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="display text-4xl leading-none font-black">
                {preview.targets_count}
              </span>
              <span className="text-muted">mensaje{preview.targets_count === 1 ? '' : 's'}</span>
            </div>
            <p className="mono mt-2 text-xs text-muted">
              ~{preview.estimate.days} día{preview.estimate.days === 1 ? '' : 's'} ·{' '}
              {preview.estimate.per_day}/día · 1 cada {fmtGap(preview.estimate.avg_delay_seconds)} ·
              franja {params.hour_start}–{params.hour_end}h
            </p>
            {/* follower split — green = safest (already follow you) */}
            {preview.targets_count > 0 && (
              <div className="mt-3">
                <div className="flex h-2 overflow-hidden rounded-full bg-panel-2">
                  <div
                    className="h-full bg-green"
                    style={{
                      width: `${Math.round((preview.follower_targets / preview.targets_count) * 100)}%`,
                    }}
                  />
                </div>
                <div className="mt-1.5 flex justify-between text-xs text-muted">
                  <span>
                    <span className="text-green">●</span> {preview.follower_targets} te siguen
                  </span>
                  <span>{preview.targets_count - preview.follower_targets} no te siguen</span>
                </div>
              </div>
            )}
          </>
        ) : (
          <span className="mono text-sm text-muted">Calculando resumen…</span>
        )}
        {preview && preview.samples.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1.5 border-t border-border pt-3 text-xs text-muted">
            {preview.samples.map((s) => (
              <li key={s.username} className="truncate">
                <b className="text-ink">@{s.username}:</b> {s.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
