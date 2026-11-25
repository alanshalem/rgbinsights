import { useMemo, useState } from 'react';
import { toApiError, type ConfigEntry } from '../api/client';
import { useConfig, useResetConfig, useUpdateConfig } from '../api/hooks';
import { useConfirm } from './ui/confirmContext';

/** The sections, in the order the screen shows them (the backend names them). */
const GROUPS = [
  'Ritmo humano',
  'Presupuesto de pedidos',
  'Frenos',
  'Lectura de datos',
  'Caché',
] as const;

const GROUP_HINT: Record<string, string> = {
  'Ritmo humano': 'Cuánto espera la app entre un pedido a Instagram y el siguiente.',
  'Presupuesto de pedidos': 'Cuántos pedidos puede hacerle a Instagram como máximo.',
  Frenos: 'Qué hace cuando Instagram pide frenar o ya está ocupado.',
  'Lectura de datos': 'Cuánto trae cada lectura (menos es más liviano para la cuenta).',
  Caché: 'Cuánto tiempo reusa lo que ya tiene antes de volver a pedirlo.',
};

const SAFE_NOTE =
  'Solo podés ir hacia lo más seguro: esperas más largas y topes más bajos que los de fábrica.';
const SAVED = 'Listo, guardado. Se aplica desde el próximo pedido a Instagram.';

const NUMBER = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2, useGrouping: false });

function fmt(value: number): string {
  return NUMBER.format(value);
}

/** Singular of the plural units: "1 pedido", "2 pedidos" (same rule as the backend). */
const ONE: Record<string, string> = {
  pedidos: 'pedido',
  posts: 'post',
  chats: 'chat',
  comentarios: 'comentario',
  personas: 'persona',
  perfiles: 'perfil',
  días: 'día',
};

function unitFor(value: number, unit: string): string {
  return value === 1 ? (ONE[unit] ?? unit) : unit;
}

function withUnit(value: number, unit: string): string {
  return unit ? `${fmt(value)} ${unitFor(value, unit)}` : fmt(value);
}

/** "2,5" or "2.5" → 2.5; anything that is not a number → null. */
function parse(text: string): number | null {
  const clean = text.trim().replace(',', '.');
  if (!clean) return null;
  const n = Number(clean);
  return Number.isFinite(n) ? n : null;
}

/** Same checks as the backend (which has the last word), shown while typing. */
function fieldError(entry: ConfigEntry, text: string): string | null {
  if (!text.trim()) return 'Completá un número.';
  const n = parse(text);
  if (n === null) return 'Tiene que ser un número.';
  if (entry.kind === 'int' && !Number.isInteger(n)) return 'Tiene que ser un número entero.';
  if (entry.min != null && n < entry.min)
    return `Mínimo ${withUnit(entry.min, entry.unit)}: no se puede ir hacia lo más rápido.`;
  if (entry.max != null && n > entry.max)
    return `Máximo ${withUnit(entry.max, entry.unit)}: no se puede pedirle más a Instagram.`;
  return null;
}

export function ConfigPage({ onBack }: { onBack: () => void }) {
  const confirm = useConfirm();
  const config = useConfig();
  const update = useUpdateConfig();
  const reset = useResetConfig();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const entries = useMemo(() => config.data?.entries ?? [], [config.data]);
  const byKey = useMemo(() => new Map(entries.map((entry) => [entry.key, entry])), [entries]);
  const textOf = (entry: ConfigEntry) => drafts[entry.key] ?? fmt(entry.value);

  // Per-field errors, plus "a minimum above its maximum" on both fields of a pair.
  // Only what you typed is checked: a value already in use may sit beyond the
  // editable range on the safe side (an old .env or saved value, kept as is).
  const errors = new Map<string, string>();
  for (const entry of entries) {
    const draft = drafts[entry.key];
    const own = draft === undefined ? null : fieldError(entry, draft);
    if (own) errors.set(entry.key, own);
  }
  for (const low of entries) {
    const high = low.at_most ? byKey.get(low.at_most) : undefined;
    if (!high || errors.has(low.key) || errors.has(high.key)) continue;
    if (drafts[low.key] === undefined && drafts[high.key] === undefined) continue;
    const a = parse(textOf(low));
    const b = parse(textOf(high));
    if (a !== null && b !== null && a > b) {
      errors.set(low.key, `No puede ser mayor que «${high.label}» (${withUnit(b, high.unit)}).`);
      errors.set(high.key, `No puede ser menor que «${low.label}» (${withUnit(a, low.unit)}).`);
    }
  }

  const changed = entries.filter((entry) => {
    const draft = drafts[entry.key];
    return draft !== undefined && parse(draft) !== entry.value;
  });
  const busy = update.isPending || reset.isPending;
  const canSave = changed.length > 0 && errors.size === 0 && !busy;

  const fail = (e: unknown) => setMessage({ ok: false, text: toApiError(e).message });
  const dropDraft = (key: string) =>
    setDrafts((d) => {
      const next = { ...d };
      delete next[key];
      return next;
    });

  const save = () => {
    if (!canSave) return;
    setMessage(null);
    const values: Record<string, number> = {};
    for (const entry of changed) values[entry.key] = parse(textOf(entry)) as number;
    update.mutate(values, {
      onSuccess: () => {
        setDrafts({});
        setMessage({ ok: true, text: SAVED });
      },
      onError: fail,
    });
  };

  const restore = (entry: ConfigEntry) => {
    setMessage(null);
    if (!entry.overridden) {
      dropDraft(entry.key); // only an unsaved edit to undo
      return;
    }
    reset.mutate(entry.key, {
      onSuccess: () => {
        dropDraft(entry.key);
        setMessage({ ok: true, text: `«${entry.label}» volvió a su valor por defecto.` });
      },
      onError: fail,
    });
  };

  const restoreAll = async () => {
    const ok = await confirm({
      title: '¿Restaurar todo?',
      message: 'Todos los ajustes vuelven a sus valores por defecto.',
      confirmLabel: 'Restaurar todo',
    });
    if (!ok) return;
    setMessage(null);
    reset.mutate(undefined, {
      onSuccess: () => {
        setDrafts({});
        setMessage({
          ok: true,
          text: 'Listo: todos los ajustes volvieron a sus valores por defecto.',
        });
      },
      onError: fail,
    });
  };

  const anyOverridden = entries.some((entry) => entry.overridden);

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="display text-2xl font-black tracking-tight uppercase">Configuración</h1>
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-panel"
        >
          ← Volver al panel
        </button>
      </div>
      <p className="mb-2 text-sm text-muted">
        Cómo trabaja la app con Instagram. Los cambios se aplican desde el próximo pedido, sin
        reiniciar nada.
      </p>
      <p className="mb-6 rounded-lg border border-green/40 bg-green/10 p-3 text-sm text-green">
        🛡 {SAFE_NOTE}
      </p>

      {config.isError ? (
        <p role="alert" className="py-12 text-center text-sm text-red">
          No se pudo leer la configuración. Cerrá la app y abrila de nuevo.
        </p>
      ) : config.isPending ? (
        <p className="py-12 text-center text-sm text-muted">Cargando…</p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
          className="flex flex-col gap-6"
        >
          {GROUPS.map((group) => {
            const fields = entries.filter((entry) => entry.group === group);
            if (fields.length === 0) return null;
            return (
              <section
                key={group}
                aria-labelledby={`grupo-${group}`}
                className="rounded-2xl border border-border bg-panel p-4"
              >
                <h2
                  id={`grupo-${group}`}
                  className="display text-lg font-black tracking-tight uppercase"
                >
                  {group}
                </h2>
                <p className="mb-3 text-xs text-muted">{GROUP_HINT[group]}</p>
                <div className="flex flex-col gap-4">
                  {fields.map((entry) => (
                    <NumberField
                      key={entry.key}
                      entry={entry}
                      text={textOf(entry)}
                      error={errors.get(entry.key) ?? null}
                      dirty={drafts[entry.key] !== undefined}
                      disabled={busy}
                      onChange={(text) => {
                        setMessage(null);
                        setDrafts((d) => ({ ...d, [entry.key]: text }));
                      }}
                      onRestore={() => restore(entry)}
                    />
                  ))}
                </div>
              </section>
            );
          })}

          <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t border-border bg-bg/90 py-3 backdrop-blur">
            <button
              type="submit"
              disabled={!canSave}
              className="rounded-lg bg-green px-4 py-2 text-sm font-semibold text-bg disabled:opacity-40"
            >
              {update.isPending ? 'Guardando…' : 'Guardar cambios'}
            </button>
            <button
              type="button"
              onClick={restoreAll}
              disabled={busy || (!anyOverridden && changed.length === 0)}
              className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-panel disabled:opacity-40"
            >
              Restaurar todo
            </button>
            {changed.length > 0 && errors.size === 0 && !message && (
              <span className="text-xs text-muted">
                {changed.length === 1
                  ? '1 cambio sin guardar'
                  : `${changed.length} cambios sin guardar`}
              </span>
            )}
            {errors.size > 0 && (
              <span className="text-xs text-red">
                Corregí los campos marcados en rojo para guardar.
              </span>
            )}
            {message && (
              <p
                role={message.ok ? 'status' : 'alert'}
                className={`text-sm ${message.ok ? 'text-green' : 'text-red'}`}
              >
                {message.ok ? '✓ ' : ''}
                {message.text}
              </p>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

function NumberField({
  entry,
  text,
  error,
  dirty,
  disabled,
  onChange,
  onRestore,
}: {
  entry: ConfigEntry;
  text: string;
  error: string | null;
  dirty: boolean;
  disabled: boolean;
  onChange: (text: string) => void;
  onRestore: () => void;
}) {
  const id = `cfg-${entry.key}`;
  // In use beyond the editable range: only ever on the safe (slower) side.
  const outOfRange =
    !dirty &&
    ((entry.min != null && entry.value < entry.min) ||
      (entry.max != null && entry.value > entry.max));
  const range =
    entry.min != null && entry.max != null
      ? `entre ${withUnit(entry.min, entry.unit)} y ${withUnit(entry.max, entry.unit)}`
      : '';
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className="text-sm font-medium">
          {entry.label}
          {entry.overridden && (
            <span className="ml-2 rounded-full border border-blue/50 px-1.5 text-[10px] text-blue uppercase">
              cambiado
            </span>
          )}
        </label>
        <p id={`${id}-help`} className="text-xs text-muted">
          {entry.help}
        </p>
      </div>
      <div className="flex w-full shrink-0 flex-col gap-1 sm:w-64">
        <div className="flex items-center gap-2">
          <input
            id={id}
            type="text"
            inputMode={entry.kind === 'int' ? 'numeric' : 'decimal'}
            value={text}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            aria-invalid={error ? true : undefined}
            aria-describedby={`${id}-help ${id}-range${error ? ` ${id}-error` : ''}`}
            className={`mono w-28 rounded-lg border bg-bg px-3 py-1.5 text-sm outline-none focus:border-muted ${
              error ? 'border-red' : 'border-border'
            }`}
          />
          <span className="text-sm text-muted">{unitFor(parse(text) ?? 0, entry.unit)}</span>
          <button
            type="button"
            onClick={onRestore}
            disabled={disabled || (!entry.overridden && !dirty)}
            aria-label={`Restaurar «${entry.label}» a su valor por defecto`}
            className="ml-auto text-xs text-muted underline hover:text-ink disabled:no-underline disabled:opacity-40"
          >
            restaurar
          </button>
        </div>
        <p id={`${id}-range`} className="text-xs text-muted">
          por defecto: {withUnit(entry.default, entry.unit)}
          {range && ` · ${range}`}
        </p>
        {entry.clamped_from != null && (
          <p className="text-xs text-yellow">
            Tu archivo .env pedía {withUnit(entry.clamped_from, entry.unit)}, que es más rápido de
            lo permitido; se usa {withUnit(entry.default, entry.unit)}.
          </p>
        )}
        {outOfRange && (
          <p className="text-xs text-yellow">
            {entry.overridden
              ? `Está guardado en ${withUnit(entry.value, entry.unit)}, fuera del rango editable. `
              : `Viene de tu archivo .env: ${withUnit(entry.value, entry.unit)}, fuera del rango editable. `}
            Se respeta porque es más seguro (más lento). Para cambiarlo, escribí un valor del rango
            y guardá{entry.overridden ? ', o tocá restaurar' : ''}.
          </p>
        )}
        {error && (
          <p id={`${id}-error`} className="text-xs text-red">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
