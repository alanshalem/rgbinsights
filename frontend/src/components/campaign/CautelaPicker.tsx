import type { CampaignPreview, Preset } from '../../api/client';
import { estimateFor, toParams } from '../../lib/campaign';
import { PRESET_LABEL, type Params } from './types';

function Field({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min: number;
  max: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mono w-full rounded-lg border border-border bg-bg px-2 py-1.5 outline-none"
      />
    </label>
  );
}

/** Cautela preset cards (Óptimo / Máxima / Media / Custom) + the custom knobs. */
export function CautelaPicker({
  presetName,
  applyPreset,
  presets,
  params,
  setParams,
  preview,
  count,
}: {
  presetName: string;
  applyPreset: (n: string) => void;
  presets: Preset[];
  params: Params;
  setParams: (p: Params) => void;
  preview: CampaignPreview | null;
  count: number;
}) {
  // Params for a given preset name (custom uses the live editable params).
  const paramsFor = (name: string): Params => {
    if (name === 'custom') return params;
    if (name === 'optimo') return preview?.optimal ? toParams(preview.optimal) : params;
    const p = presets.find((x) => x.name === name);
    return p ? toParams(p) : params;
  };
  const cards = ['optimo', ...presets.map((p) => p.name), 'custom'];

  return (
    <>
      <div className="flex flex-col gap-1.5">
        <span className="text-muted">Cautela (ritmo de envío)</span>
        <div className="grid gap-2 sm:grid-cols-2">
          {/* the first card is the auto-computed sweet spot */}
          {cards.map((name) => {
            const p = paramsFor(name);
            const est = estimateFor(count, p);
            const selected = presetName === name;
            return (
              <button
                type="button"
                key={name}
                onClick={() => applyPreset(name)}
                className={`flex flex-col gap-1 rounded-lg border px-3 py-2 text-left ${
                  selected ? 'border-blue bg-blue/10' : 'border-border hover:border-muted'
                }`}
              >
                <span className="font-semibold">{PRESET_LABEL[name] ?? name}</span>
                <span className="mono text-xs text-muted">
                  {p.delay_min}–{p.delay_max}s · {p.daily_cap}/día · {p.hour_start}–{p.hour_end}h
                </span>
                <span className="mono text-xs">
                  {count > 0 ? `~${est.days} día${est.days === 1 ? '' : 's'}` : 'sin rojos'}
                </span>
              </button>
            );
          })}
        </div>
        <span className="text-xs text-muted">
          <b>Óptimo</b>: la app calcula el ritmo más seguro que igual termina en ~2-3 días, según
          cuántos rojos haya. Si son muchos, respeta un tope diario y puede tardar un poco más.
        </span>
      </div>

      {presetName === 'custom' && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Field
            label="delay min (s)"
            value={params.delay_min}
            onChange={(n) => setParams({ ...params, delay_min: n })}
            min={10}
            max={3600}
          />
          <Field
            label="delay max (s)"
            value={params.delay_max}
            onChange={(n) => setParams({ ...params, delay_max: n })}
            min={10}
            max={3600}
          />
          <Field
            label="tope/día"
            value={params.daily_cap}
            onChange={(n) => setParams({ ...params, daily_cap: n })}
            min={1}
            max={200}
          />
          <Field
            label="hora inicio"
            value={params.hour_start}
            onChange={(n) => setParams({ ...params, hour_start: n })}
            min={0}
            max={23}
          />
          <Field
            label="hora fin"
            value={params.hour_end}
            onChange={(n) => setParams({ ...params, hour_end: n })}
            min={1}
            max={24}
          />
        </div>
      )}
    </>
  );
}
