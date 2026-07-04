import { useEffect, useRef, useState } from 'react';
import { useIsMutating, useQueryClient } from '@tanstack/react-query';
import type { Campaign, Task } from '../api/client';
import { useActiveCampaign, useTasks } from '../api/hooks';

function summary(result: Record<string, number>): string {
  return Object.entries(result)
    .map(([k, v]) => `${v} ${k}`)
    .join(' · ');
}

function Spinner() {
  return (
    <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-[var(--color-blue)] border-t-transparent" />
  );
}

function TaskToast({ task }: { task: Task }) {
  const pct = task.total > 0 ? Math.round((task.current / task.total) * 100) : null;
  const accent =
    task.status === 'error'
      ? 'var(--color-red)'
      : task.status === 'done'
        ? 'var(--color-green)'
        : 'var(--color-blue)';

  return (
    <div
      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-3 shadow-lg"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="flex items-center gap-2">
        {task.status === 'running' && <Spinner />}
        {task.status === 'done' && <span className="text-[var(--color-green)]">✓</span>}
        {task.status === 'error' && <span className="text-[var(--color-red)]">✕</span>}
        <span className="flex-1 truncate text-sm font-semibold">{task.label}</span>
        {task.total > 0 && task.status === 'running' && (
          <span className="mono shrink-0 text-xs text-[var(--color-muted)]">
            {task.current}/{task.total}
          </span>
        )}
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
        <p className="mono mt-1 text-xs text-[var(--color-green)]">
          {summary(task.result as Record<string, number>) || 'listo'}
        </p>
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
  const accent = c.status === 'blocked' ? 'var(--color-red)' : 'var(--color-red)';
  return (
    <div
      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-3 shadow-lg"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="flex items-center gap-2">
        {c.status === 'running' && <Spinner />}
        <span className="flex-1 truncate text-sm font-semibold">✉ Campaña de DMs</span>
        <span className="mono shrink-0 text-xs text-[var(--color-muted)]">
          {c.sent}/{c.total}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--color-panel-2)]">
        <div
          className="h-full rounded-full bg-[var(--color-red)] transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mono mt-1 text-xs text-[var(--color-muted)]">
        {c.status === 'blocked'
          ? `frenada: ${c.error}`
          : `${c.status} · hoy ${c.sent_today}/${c.daily_cap}`}
      </p>
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
