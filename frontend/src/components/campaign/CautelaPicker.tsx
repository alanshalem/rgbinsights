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

/** Pace preset cards (Máxima cautela / Media / Automático / A mano) + the
 * "A mano" knobs. The recommended (safest) one comes first. */
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
  const cards = [...presets.map((p) => p.name), 'optimo', 'custom'];

  return (
    <>
      <div className="flex flex-col gap-1.5">
        <span className="text-muted">Velocidad de envío (más lento = más seguro)</span>
        <div className="grid gap-2 sm:grid-cols-2">
          {cards.map((name) => {
            const p = paramsFor(name);
            const est = estimateFor(count, p);
            const selected = presetName === name;
            return (
              <button
                type="button"
                key={name}
                onClick={() => applyPreset(name)}
                aria-pressed={selected}
                className={`flex flex-col gap-1 rounded-lg border px-3 py-2 text-left ${
                  selected ? 'border-blue bg-blue/10' : 'border-border hover:border-muted'
                }`}
              >
                <span className="font-semibold">{PRESET_LABEL[name] ?? name}</span>
                <span className="text-xs text-muted">
                  1 DM cada {p.delay_min}–{p.delay_max} seg · hasta {p.daily_cap} por día · de{' '}
                  {p.hour_start} a {p.hour_end} h
                </span>
                <span className="text-xs">
                  {count > 0
                    ? `Tarda ~${est.days} día${est.days === 1 ? '' : 's'}`
                    : 'No hay rojos para mandar'}
                </span>
              </button>
            );
          })}
        </div>
        <span className="text-xs text-muted">
          <b>Máxima cautela</b> es lo recomendado. <b>Automático</b>: la app calcula el ritmo para
          terminar en ~2-3 días según cuántos rojos haya (con un tope por día); con listas grandes
          manda más DMs por día que Máxima cautela, o sea más riesgo. Las horas son de Argentina.
        </span>
      </div>

      {presetName === 'custom' && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Field
            label="Espera mínima entre DMs (seg)"
            value={params.delay_min}
            onChange={(n) => setParams({ ...params, delay_min: n })}
            min={10}
            max={3600}
          />
          <Field
            label="Espera máxima entre DMs (seg)"
            value={params.delay_max}
            onChange={(n) => setParams({ ...params, delay_max: n })}
            min={10}
            max={3600}
          />
          <Field
            label="Máximo por día"
            value={params.daily_cap}
            onChange={(n) => setParams({ ...params, daily_cap: n })}
            min={1}
            max={200}
          />
          <Field
            label="Desde (hora)"
            value={params.hour_start}
            onChange={(n) => setParams({ ...params, hour_start: n })}
            min={0}
            max={23}
          />
          <Field
            label="Hasta (hora)"
            value={params.hour_end}
            onChange={(n) => setParams({ ...params, hour_end: n })}
            min={1}
            max={24}
          />
          {params.delay_max < params.delay_min && (
            <p role="alert" className="col-span-full text-xs text-red">
              La espera máxima tiene que ser igual o mayor que la mínima.
            </p>
          )}
          {params.hour_end <= params.hour_start && (
            <p role="alert" className="col-span-full text-xs text-red">
              La hora “Hasta” tiene que ser después de “Desde”.
            </p>
          )}
        </div>
      )}
    </>
  );
}
