import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ApiError,
  api,
  type Campaign,
  type CampaignCreate,
  type CampaignPreview,
} from '../api/client';
import { useCampaign, usePresets, useResumeCampaign, useStopCampaign } from '../api/hooks';

type Params = {
  delay_min: number;
  delay_max: number;
  daily_cap: number;
  hour_start: number;
  hour_end: number;
};

const DEFAULT_MSG =
  'Hola {nombre}, ¿cómo estás? Vi que te copó RGB 🔴🟢🔵 — se viene fecha nueva y te queríamos invitar. Cualquier cosa te paso la data 🙌';

const PRESET_LABEL: Record<string, string> = { max: 'Máxima cautela', media: 'Media cautela' };

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
      <span className="text-[var(--color-muted)]">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mono w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1.5 outline-none"
      />
    </label>
  );
}

export function CampaignModal({
  event,
  eventName,
  onClose,
}: {
  event: number;
  eventName: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const presets = usePresets();
  const campaign = useCampaign(event);
  const stop = useStopCampaign();
  const resume = useResumeCampaign();

  const [templates, setTemplates] = useState<string[]>([DEFAULT_MSG, '', '']);
  const [presetName, setPresetName] = useState<string>('max');
  const [params, setParams] = useState<Params>({
    delay_min: 60,
    delay_max: 180,
    daily_cap: 25,
    hour_start: 11,
    hour_end: 23,
  });
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testedTo, setTestedTo] = useState<string | null>(null);
  const [onlyFollowers, setOnlyFollowers] = useState(false);
  const [followersFirst, setFollowersFirst] = useState(true);

  const active = campaign.data;
  const showProgress = active != null && ['running', 'paused', 'blocked'].includes(active.status);

  const body: CampaignCreate = useMemo(
    () => ({
      templates: templates.map((t) => t.trim()).filter(Boolean),
      ...params,
      only_followers: onlyFollowers,
      followers_first: followersFirst,
    }),
    [templates, params, onlyFollowers, followersFirst]
  );

  // Apply a preset's params.
  const applyPreset = (name: string) => {
    setPresetName(name);
    if (name === 'custom') return;
    const p = presets.data?.find((x) => x.name === name);
    if (p)
      setParams({
        delay_min: p.delay_min,
        delay_max: p.delay_max,
        daily_cap: p.daily_cap,
        hour_start: p.hour_start,
        hour_end: p.hour_end,
      });
  };

  const previewMut = useMutation({
    mutationFn: () => api.previewCampaign(event, body),
    onSuccess: setPreview,
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });
  const testMut = useMutation({
    mutationFn: () => api.testCampaign(event, body),
    onSuccess: (r) => setTestedTo(r.username),
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });
  const createMut = useMutation({
    mutationFn: () => api.createCampaign(event, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['campaign'] });
      void qc.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });

  // First preview once presets/params are ready, when in setup mode.
  useEffect(() => {
    if (!showProgress && body.templates.length > 0 && preview === null) previewMut.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showProgress]);

  const launch = () => {
    setError(null);
    const n = preview?.targets_count ?? 0;
    if (
      !confirm(
        `Vas a enviar DMs a ${n} usuarios rojos de "${eventName}". Enviar masivo tiene riesgo de ban. ¿Confirmás?`
      )
    )
      return;
    createMut.mutate();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="my-8 h-fit w-full max-w-2xl rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="display text-xl font-black tracking-tight uppercase">Campaña de DMs</h2>
          <button
            onClick={onClose}
            className="rounded-lg bg-[var(--color-panel-2)] px-3 py-1 text-sm hover:bg-[var(--color-border)]"
          >
            Cerrar
          </button>
        </div>

        {showProgress && active ? (
          <Progress
            c={active}
            onStop={() => stop.mutate(active.id)}
            onResume={() => resume.mutate(active.id)}
            busy={stop.isPending || resume.isPending}
          />
        ) : (
          <Setup
            eventName={eventName}
            templates={templates}
            setTemplates={setTemplates}
            presetName={presetName}
            applyPreset={applyPreset}
            presetNames={(presets.data ?? []).map((p) => p.name)}
            params={params}
            setParams={setParams}
            onlyFollowers={onlyFollowers}
            setOnlyFollowers={setOnlyFollowers}
            followersFirst={followersFirst}
            setFollowersFirst={setFollowersFirst}
            preview={preview}
            recalc={() => {
              setError(null);
              previewMut.mutate();
            }}
            recalcBusy={previewMut.isPending}
            onTest={() => {
              setTestedTo(null);
              setError(null);
              testMut.mutate();
            }}
            testBusy={testMut.isPending}
            testedTo={testedTo}
            onLaunch={launch}
            launchBusy={createMut.isPending}
            error={error}
          />
        )}
      </div>
    </div>
  );
}

function Progress({
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
    running: 'text-[var(--color-green)]',
    paused: 'text-[var(--color-yellow)]',
    blocked: 'text-[var(--color-red)]',
    done: 'text-[var(--color-muted)]',
  };
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex items-center gap-2">
        <span className={`mono font-bold uppercase ${badge[c.status]}`}>{c.status}</span>
        <span className="mono text-[var(--color-muted)]">
          {c.sent} enviados · {c.pending} pendientes · {c.failed} fallidos
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--color-panel-2)]">
        <div className="h-full rounded-full bg-[var(--color-green)]" style={{ width: `${pct}%` }} />
      </div>
      <p className="mono text-xs text-[var(--color-muted)]">
        hoy {c.sent_today}/{c.daily_cap} · 1 cada {c.delay_min}-{c.delay_max}s · {c.hour_start}-
        {c.hour_end}h
      </p>
      {c.status === 'blocked' && (
        <p className="rounded-lg border border-[var(--color-red)]/50 bg-[var(--color-red)]/10 px-3 py-2 text-xs text-[var(--color-red)]">
          Instagram frenó el envío: {c.error}. Esperá un rato (horas), y si querés reanudá.
        </p>
      )}
      <div className="flex gap-2">
        {c.status === 'running' ? (
          <button
            onClick={onStop}
            disabled={busy}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 font-semibold disabled:opacity-40"
          >
            Pausar
          </button>
        ) : (
          <button
            onClick={onResume}
            disabled={busy || c.pending === 0}
            className="rounded-lg bg-[var(--color-green)] px-4 py-2 font-semibold text-[var(--color-bg)] disabled:opacity-40"
          >
            Reanudar
          </button>
        )}
      </div>
      <p className="text-xs text-[var(--color-muted)]">
        La campaña sigue en segundo plano mientras el backend esté corriendo. Podés cerrar esta
        ventana.
      </p>
    </div>
  );
}

function Setup(props: {
  eventName: string;
  templates: string[];
  setTemplates: (t: string[]) => void;
  presetName: string;
  applyPreset: (n: string) => void;
  presetNames: string[];
  params: Params;
  setParams: (p: Params) => void;
  onlyFollowers: boolean;
  setOnlyFollowers: (b: boolean) => void;
  followersFirst: boolean;
  setFollowersFirst: (b: boolean) => void;
  preview: CampaignPreview | null;
  recalc: () => void;
  recalcBusy: boolean;
  onTest: () => void;
  testBusy: boolean;
  testedTo: string | null;
  onLaunch: () => void;
  launchBusy: boolean;
  error: string | null;
}) {
  const {
    eventName,
    templates,
    setTemplates,
    presetName,
    applyPreset,
    presetNames,
    params,
    setParams,
    onlyFollowers,
    setOnlyFollowers,
    followersFirst,
    setFollowersFirst,
    preview,
    recalc,
    recalcBusy,
    onTest,
    testBusy,
    testedTo,
    onLaunch,
    launchBusy,
    error,
  } = props;
  const avgMin = preview ? Math.round(preview.estimate.avg_delay_seconds / 60) : null;

  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="rounded-lg border border-[var(--color-red)]/50 bg-[var(--color-red)]/10 px-3 py-2 text-xs text-[var(--color-red)]">
        <b>Riesgo:</b> enviar DMs masivos es la acción más riesgosa de Instagram. Aún con cautela
        hay riesgo de <b>action-block o ban</b>. Se frena solo si IG avisa. Empezá con “Máxima
        cautela” y no lo hagas todos los días.
      </div>

      {/* message variants */}
      <div className="flex flex-col gap-2">
        <span className="text-[var(--color-muted)]">
          Mensaje ({templates.filter((t) => t.trim()).length} variante(s)) — usá{' '}
          <code>{'{nombre}'}</code> y <code>{'{usuario}'}</code>. Varias variantes = menos spam.
        </span>
        {templates.map((t, i) => (
          <textarea
            key={i}
            value={t}
            onChange={(e) => {
              const next = [...templates];
              next[i] = e.target.value;
              setTemplates(next);
            }}
            rows={2}
            placeholder={i === 0 ? 'Mensaje principal…' : 'Variante (opcional)…'}
            className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 outline-none"
          />
        ))}
      </div>

      {/* presets */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[var(--color-muted)]">Cautela:</span>
        {presetNames.map((name) => (
          <button
            key={name}
            onClick={() => applyPreset(name)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
              presetName === name
                ? 'bg-[var(--color-blue)] text-[var(--color-bg)]'
                : 'border border-[var(--color-border)]'
            }`}
          >
            {PRESET_LABEL[name] ?? name}
          </button>
        ))}
        <button
          onClick={() => applyPreset('custom')}
          className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
            presetName === 'custom'
              ? 'bg-[var(--color-blue)] text-[var(--color-bg)]'
              : 'border border-[var(--color-border)]'
          }`}
        >
          Custom
        </button>
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

      {/* follow-status safety options */}
      <div className="flex flex-wrap gap-4 text-xs">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={onlyFollowers}
            onChange={(e) => setOnlyFollowers(e.target.checked)}
          />
          <span>
            Solo a los que <b>me siguen</b> (más seguro)
          </span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={followersFirst}
            onChange={(e) => setFollowersFirst(e.target.checked)}
          />
          <span>Seguidores primero</span>
        </label>
      </div>

      {/* estimate + preview */}
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-3">
        <div className="flex items-center justify-between">
          <span className="mono text-sm">
            {preview ? (
              <>
                <b>{preview.targets_count}</b> rojos · ~<b>{preview.estimate.days}</b> día(s) ·{' '}
                {preview.estimate.per_day}/día · 1 cada ~{avgMin}min
              </>
            ) : (
              'Calculá el resumen…'
            )}
          </span>
          <button
            onClick={recalc}
            disabled={recalcBusy}
            className="rounded-lg border border-[var(--color-border)] px-3 py-1 text-xs disabled:opacity-40"
          >
            {recalcBusy ? '…' : 'Recalcular'}
          </button>
        </div>
        {preview && preview.samples.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1 text-xs text-[var(--color-muted)]">
            {preview.samples.map((s) => (
              <li key={s.username} className="truncate">
                <b>@{s.username}:</b> {s.message}
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <p className="text-xs text-[var(--color-red)]">{error}</p>}
      {testedTo && (
        <p className="text-xs text-[var(--color-green)]">
          ✓ Mensaje de prueba enviado a @{testedTo}.
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <button
          onClick={onTest}
          disabled={testBusy || (preview?.targets_count ?? 0) === 0}
          className="rounded-lg border border-[var(--color-border)] px-4 py-2 font-semibold disabled:opacity-40"
        >
          {testBusy ? 'Enviando…' : 'Enviar 1 de prueba'}
        </button>
        <button
          onClick={onLaunch}
          disabled={launchBusy || (preview?.targets_count ?? 0) === 0}
          className="rounded-lg bg-[var(--color-red)] px-4 py-2 font-semibold text-[var(--color-bg)] shadow-[0_0_24px_-6px_var(--color-red)] disabled:opacity-40"
        >
          {launchBusy ? 'Lanzando…' : `Lanzar campaña (${eventName})`}
        </button>
      </div>
    </div>
  );
}
