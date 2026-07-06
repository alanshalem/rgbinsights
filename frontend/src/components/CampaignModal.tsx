import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  api,
  toApiError,
  type Campaign,
  type CampaignCreate,
  type CampaignPreview,
  type Preset,
} from '../api/client';
import {
  useCampaign,
  usePresets,
  useResumeCampaign,
  useStopCampaign,
  useUsers,
} from '../api/hooks';
import { estimateFor, fmtGap, toParams, type SendParams } from '../lib/campaign';
import { Modal } from './Modal';

type Params = SendParams;

/** How the red list is filtered/ordered by follow status. */
type Audience = 'only' | 'first' | 'all';

const DEFAULT_MSG =
  'Hola {nombre}, ¿cómo estás? Vi que te copó RGB 🔴🟢🔵 — se viene fecha nueva y te queríamos invitar. Cualquier cosa te paso la data 🙌';

const PRESET_LABEL: Record<string, string> = {
  optimo: 'Óptimo (recomendado)',
  max: 'Máxima cautela',
  media: 'Media cautela',
  custom: 'Custom',
};

const AUDIENCE: { key: Audience; label: string; hint: string }[] = [
  {
    key: 'only',
    label: 'Solo a los que me siguen',
    hint: 'Lo más seguro: casi nunca bloquean un DM a un seguidor. Llega a menos gente.',
  },
  {
    key: 'first',
    label: 'Seguidores primero (recomendado)',
    hint: 'Le manda a todos los rojos, pero arranca por los que te siguen. Equilibra alcance y riesgo.',
  },
  {
    key: 'all',
    label: 'Todos, sin orden',
    hint: 'Todos los rojos en el orden del board. Máximo alcance, más riesgo.',
  },
];

function audienceToFlags(a: Audience): { only_followers: boolean; followers_first: boolean } {
  return {
    only_followers: a === 'only',
    followers_first: a === 'only' || a === 'first',
  };
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
  const [audience, setAudience] = useState<Audience>('first');
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testedTo, setTestedTo] = useState<string | null>(null);
  const [testTarget, setTestTarget] = useState('');

  const active = campaign.data;
  const showProgress = active != null && ['running', 'paused', 'blocked'].includes(active.status);

  const flags = audienceToFlags(audience);
  const body: CampaignCreate = useMemo(
    () => ({
      templates: templates.map((t) => t.trim()).filter(Boolean),
      ...params,
      ...audienceToFlags(audience),
    }),
    [templates, params, audience]
  );

  // Red list for the test-send picker (respects the audience follow filter).
  const reds = useUsers({
    event,
    status: 'red',
    follows: flags.only_followers ? true : undefined,
    order: 'followers',
    limit: 500,
  });
  const redUsers = reds.data ?? [];

  const applyPreset = (name: string) => {
    setPresetName(name);
    if (name === 'custom') return;
    // "Óptimo" is computed by the backend from the target count (finish in ~2-3
    // days at the safest pace); it rides on the preview response.
    const chosen =
      name === 'optimo' ? preview?.optimal : presets.data?.find((x) => x.name === name);
    if (chosen) setParams(toParams(chosen));
  };

  const previewMut = useMutation({
    mutationFn: () => api.previewCampaign(event, body),
    onSuccess: setPreview,
    onError: (e) => setError(toApiError(e).message),
  });
  const testMut = useMutation({
    mutationFn: () => api.testCampaign(event, body, testTarget.trim() || undefined),
    onSuccess: (r) => setTestedTo(r.username),
    onError: (e) => setError(toApiError(e).message),
  });
  const createMut = useMutation({
    mutationFn: () => api.createCampaign(event, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['campaign'] });
      void qc.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e) => setError(toApiError(e).message),
  });

  // Recalc whenever the audience or send params change (not on every keystroke
  // in the message — those are picked up by the Recalcular button).
  const settingsKey = JSON.stringify({ ...params, audience });
  useEffect(() => {
    if (!showProgress && body.templates.length > 0) previewMut.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsKey, showProgress]);

  // Keep "Óptimo" in sync: if the target count changes (e.g. the audience
  // filter), re-apply the freshly computed sweet-spot params.
  const optimalCap = preview?.optimal?.daily_cap;
  const optimalDelay = preview?.optimal?.delay_min;
  useEffect(() => {
    if (presetName === 'optimo' && preview?.optimal) applyPreset('optimo');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimalCap, optimalDelay]);

  const launch = () => {
    setError(null);
    const n = preview?.targets_count ?? 0;
    if (
      !confirm(
        `Vas a enviar DMs a ${n} rojos de "${eventName}". Enviar masivo tiene riesgo de ban. ¿Confirmás?`
      )
    )
      return;
    createMut.mutate();
  };

  return (
    <Modal onClose={onClose} size="xl">
      <div>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <h2 className="display text-xl font-black tracking-tight uppercase">Campaña de DMs</h2>
            <span className="mono text-xs text-muted">{eventName}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg bg-panel-2 px-3 py-1 text-sm hover:bg-border"
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
            templates={templates}
            setTemplates={setTemplates}
            presetName={presetName}
            applyPreset={applyPreset}
            presets={presets.data ?? []}
            params={params}
            setParams={setParams}
            audience={audience}
            setAudience={setAudience}
            redUsers={redUsers}
            testTarget={testTarget}
            setTestTarget={setTestTarget}
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
    </Modal>
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

function Setup(props: {
  templates: string[];
  setTemplates: (t: string[]) => void;
  presetName: string;
  applyPreset: (n: string) => void;
  presets: Preset[];
  params: Params;
  setParams: (p: Params) => void;
  audience: Audience;
  setAudience: (a: Audience) => void;
  redUsers: { username: string; follows_us?: boolean | null }[];
  testTarget: string;
  setTestTarget: (s: string) => void;
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
    templates,
    setTemplates,
    presetName,
    applyPreset,
    presets,
    params,
    setParams,
    audience,
    setAudience,
    redUsers,
    testTarget,
    setTestTarget,
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

  const count = preview?.targets_count ?? redUsers.length;
  const variants = templates.filter((t) => t.trim());
  const usesName = variants.some((t) => /\{nombre\}|\{usuario\}|\{username\}/.test(t));

  // Params for a given preset name (custom uses the live editable params).
  const paramsFor = (name: string): Params => {
    if (name === 'custom') return params;
    if (name === 'optimo') return preview?.optimal ? toParams(preview.optimal) : params;
    const p = presets.find((x) => x.name === name);
    return p ? toParams(p) : params;
  };
  const cards = ['optimo', ...presets.map((p) => p.name), 'custom'];

  return (
    <div className="grid gap-6 text-sm lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
      {/* ================= LEFT: componer ================= */}
      <div className="flex min-w-0 flex-col gap-6">
        {/* message variants */}
        <div className="flex flex-col gap-2">
          <span className="text-muted">
            Mensaje ({variants.length} variante{variants.length === 1 ? '' : 's'}) — usá{' '}
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
              className="w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 outline-none"
            />
          ))}
          {variants.length > 0 && !usesName && (
            <p className="text-xs text-yellow">
              ⚠ Sin <code>{'{nombre}'}</code> todos reciben el mismo texto exacto — más señal de
              spam.
            </p>
          )}
        </div>

        {/* audience — follow-status filter, explained */}
        <div className="flex flex-col gap-1.5">
          <span className="text-muted">¿A quién le mando?</span>
          {AUDIENCE.map((a) => (
            <label
              key={a.key}
              className={`flex cursor-pointer gap-2 rounded-lg border px-3 py-2 ${
                audience === a.key ? 'border-blue bg-blue/10' : 'border-border'
              }`}
            >
              <input
                type="radio"
                name="audience"
                checked={audience === a.key}
                onChange={() => setAudience(a.key)}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold">{a.label}</span>
                <span className="block text-xs text-muted">{a.hint}</span>
              </span>
            </label>
          ))}
        </div>

        {/* cautela presets — each card shows its knobs + ETA */}
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
      </div>

      {/* ================= RIGHT: revisar + lanzar ================= */}
      <aside className="flex min-w-0 flex-col gap-3">
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
                {preview.estimate.per_day}/día · 1 cada {fmtGap(preview.estimate.avg_delay_seconds)}{' '}
                · franja {params.hour_start}–{params.hour_end}h
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

        {error && <p className="text-xs text-red">{error}</p>}
        {testedTo && (
          <p className="text-xs text-green">✓ Mensaje de prueba enviado a @{testedTo}.</p>
        )}

        {/* test send — one DM to check it lands before the batch */}
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-bg p-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted">
              Probá primero: mandá 1 DM (por defecto, al primero de la lista)
            </span>
            <input
              list="test-targets"
              value={testTarget}
              onChange={(e) => setTestTarget(e.target.value)}
              placeholder={redUsers[0] ? `@${redUsers[0].username}` : '@usuario'}
              className="w-full rounded-lg border border-border bg-panel px-3 py-2 outline-none"
            />
            <datalist id="test-targets">
              {redUsers.slice(0, 500).map((u) => (
                <option key={u.username} value={u.username}>
                  {u.follows_us ? 'te sigue' : ''}
                </option>
              ))}
            </datalist>
          </label>
          <button
            type="button"
            onClick={onTest}
            disabled={testBusy || count === 0}
            className="w-full rounded-lg border border-border px-4 py-2 font-semibold hover:bg-panel disabled:opacity-40"
          >
            {testBusy ? 'Enviando…' : 'Enviar 1 de prueba'}
          </button>
        </div>

        <button
          type="button"
          onClick={onLaunch}
          disabled={launchBusy || count === 0}
          className="w-full rounded-xl bg-red px-4 py-3 font-semibold text-bg shadow-[0_0_28px_-8px_var(--color-red)] transition hover:brightness-110 disabled:opacity-40"
        >
          {launchBusy ? 'Lanzando…' : `Lanzar campaña · ${count} DMs`}
        </button>
      </aside>
    </div>
  );
}

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
