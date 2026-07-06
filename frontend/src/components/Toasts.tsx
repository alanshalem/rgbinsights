import { useEffect, useRef, useState } from 'react';
import { useIsMutating, useQueryClient } from '@tanstack/react-query';
import type { Campaign, Task } from '../api/client';
import { useActiveCampaign, useTasks } from '../api/hooks';
import { estimateFor } from '../lib/campaign';

const KIND: Record<string, { icon: string; title: string }> = {
  sync: { icon: '🔄', title: 'Sincronizar DMs' },
  refresh: { icon: '↻', title: 'Actualizar fiesta' },
  enrich: { icon: '👥', title: 'Relación + perfiles' },
  scan: { icon: '🔍', title: 'Escanear posts' },
};

// Colour the outcome chips by what they mean (green = replied, red = to contact…).
const CHIP_COLOR: Record<string, string> = {
  respondieron: 'var(--color-green)',
  amarillos: 'var(--color-yellow)',
  'rojos nuevos': 'var(--color-red)',
  nuevos: 'var(--color-blue)',
  'te siguen': 'var(--color-blue)',
};

// Keys that represent "something changed" — their absence means a quiet run.
const CHANGE_KEYS = ['respondieron', 'amarillos', 'nuevos', 'rojos nuevos'];

function fmtDur(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function Spinner() {
  return (
    <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-[var(--color-blue)] border-t-transparent" />
  );
}

/** The final numbers, as little pills: bold value + Spanish label. */
function StatChips({ kind, result }: { kind: string; result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(
    ([, v]) => v !== null && v !== undefined && v !== ''
  );
  // For scan-like ops with nothing new to show, say so plainly.
  const quiet =
    ['sync', 'refresh', 'scan'].includes(kind) && !CHANGE_KEYS.some((k) => Number(result[k]) > 0);

  return (
    <>
      {quiet && <p className="mono mt-1.5 text-xs text-[var(--color-muted)]">sin novedades ·</p>}
      {entries.length === 0 ? (
        !quiet && <p className="mono mt-1 text-xs text-[var(--color-green)]">listo</p>
      ) : (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {entries.map(([k, v]) => (
            <span
              key={k}
              className="rounded-md bg-[var(--color-panel-2)] px-2 py-0.5 text-xs whitespace-nowrap"
            >
              <b style={{ color: CHIP_COLOR[k] ?? 'var(--color-ink)' }}>{String(v)}</b>{' '}
              <span className="text-[var(--color-muted)]">{k}</span>
            </span>
          ))}
        </div>
      )}
    </>
  );
}

function TaskToast({ task }: { task: Task }) {
  const meta = KIND[task.kind] ?? { icon: '•', title: task.label };
  const pct = task.total > 0 ? Math.round((task.current / task.total) * 100) : null;
  const accent =
    task.status === 'error'
      ? 'var(--color-red)'
      : task.status === 'done'
        ? 'var(--color-green)'
        : 'var(--color-blue)';

  const started = new Date(task.started_at).getTime();
  const elapsed = (task.finished_at ? new Date(task.finished_at).getTime() : Date.now()) - started;

  return (
    <div
      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-3 shadow-lg"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="flex items-center gap-2">
        {task.status === 'running' ? (
          <Spinner />
        ) : task.status === 'done' ? (
          <span className="text-[var(--color-green)]">✓</span>
        ) : (
          <span className="text-[var(--color-red)]">✕</span>
        )}
        <span className="flex-1 truncate text-sm font-semibold">
          {meta.icon} {meta.title}
        </span>
        <span className="mono shrink-0 text-xs text-[var(--color-muted)]">
          {task.status === 'running'
            ? task.total > 0
              ? `${task.current}/${task.total}`
              : fmtDur(elapsed)
            : `en ${fmtDur(elapsed)}`}
        </span>
      </div>

      {task.status === 'running' && task.total > 0 && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--color-panel-2)]">
          <div
            className="h-full rounded-full bg-[var(--color-blue)] transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {task.status === 'running' && task.message && (
        <p className="mono mt-1.5 truncate text-xs text-[var(--color-muted)]">{task.message}</p>
      )}
      {task.status === 'done' && (
        <StatChips kind={task.kind} result={task.result as Record<string, unknown>} />
      )}
      {task.status === 'error' && (
        <p className="mt-1 text-xs text-[var(--color-red)]">{task.error}</p>
      )}
    </div>
  );
}

function CampaignToast({ c }: { c: Campaign }) {
  const done = c.sent + c.failed;
  const pct = c.total ? Math.round((done / c.total) * 100) : 0;
  // Rough finish estimate from the remaining sends at the campaign's own pace.
  const eta = c.status === 'running' && c.pending > 0 ? estimateFor(c.pending, c).days : null;
  return (
    <div
      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-3 shadow-lg"
      style={{ borderLeft: '3px solid var(--color-red)' }}
    >
      <div className="flex items-center gap-2">
        {c.status === 'running' && <Spinner />}
        <span className="flex-1 truncate text-sm font-semibold">✉ Campaña de DMs</span>
        <span className="mono shrink-0 text-xs text-[var(--color-muted)]">
          {eta ? `~${eta} día${eta === 1 ? '' : 's'} · ` : ''}
          {c.sent}/{c.total}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--color-panel-2)]">
        <div
          className="h-full rounded-full bg-[var(--color-red)] transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        <span className="rounded-md bg-[var(--color-panel-2)] px-2 py-0.5">
          <b className="text-[var(--color-green)]">{c.sent}</b>{' '}
          <span className="text-[var(--color-muted)]">enviados</span>
        </span>
        {c.failed > 0 && (
          <span className="rounded-md bg-[var(--color-panel-2)] px-2 py-0.5">
            <b className="text-[var(--color-red)]">{c.failed}</b>{' '}
            <span className="text-[var(--color-muted)]">fallidos</span>
          </span>
        )}
        <span className="rounded-md bg-[var(--color-panel-2)] px-2 py-0.5">
          <b className="text-[var(--color-ink)]">{c.pending}</b>{' '}
          <span className="text-[var(--color-muted)]">pendientes</span>
        </span>
        <span className="rounded-md bg-[var(--color-panel-2)] px-2 py-0.5">
          <b className="text-[var(--color-ink)]">
            {c.sent_today}/{c.daily_cap}
          </b>{' '}
          <span className="text-[var(--color-muted)]">hoy</span>
        </span>
      </div>
      {c.status === 'blocked' && (
        <p className="mono mt-1.5 text-xs text-[var(--color-red)]">frenada: {c.error}</p>
      )}
    </div>
  );
}

export function Toasts() {
  const qc = useQueryClient();
  const active = useIsMutating() > 0;
  const tasks = useTasks(active);
  const campaign = useActiveCampaign(active);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const processed = useRef<Set<string>>(new Set());

  useEffect(() => {
    for (const t of tasks.data ?? []) {
      if ((t.status === 'done' || t.status === 'error') && !processed.current.has(t.id)) {
        processed.current.add(t.id);
        if (t.status === 'done') {
          void qc.invalidateQueries({ queryKey: ['users'] });
          void qc.invalidateQueries({ queryKey: ['counts'] });
          void qc.invalidateQueries({ queryKey: ['posts'] });
          void qc.invalidateQueries({ queryKey: ['events'] });
        }
        const id = t.id;
        setTimeout(() => setDismissed((s) => new Set(s).add(id)), 7000);
      }
    }
  }, [tasks.data, qc]);

  const visible = (tasks.data ?? []).filter((t) => !dismissed.has(t.id));
  const camp = campaign.data;
  const showCamp = camp != null && camp.status !== 'done';
  if (visible.length === 0 && !showCamp) return null;

  return (
    <div className="fixed right-4 bottom-4 z-40 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {showCamp && camp && <CampaignToast c={camp} />}
      {visible.map((t) => (
        <TaskToast key={t.id} task={t} />
      ))}
    </div>
  );
}
