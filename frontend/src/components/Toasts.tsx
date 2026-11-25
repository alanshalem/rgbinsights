import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useIsMutating, useQueryClient } from '@tanstack/react-query';
import type { Campaign, Task } from '../api/client';
import { refreshAfterJob, useActiveCampaign, useTasks, useTaskStream } from '../api/hooks';
import { campaignStatus, estimateFor } from '../lib/campaign';
import { kindMeta } from '../lib/jobs';
import { dismissNotice, useNotices, type Notice } from '../lib/notices';

/** A finished (ok) task's toast goes away by itself; an error stays until ✕. */
const DONE_SHOW_MS = 7000;

// Old backends put the warning inside the result; it is never a number chip.
const LEGACY_WARNING_KEY = 'aviso';

// Colour the outcome chips by what they mean (green = replied, red = to contact…).
const CHIP_COLOR: Record<string, string> = {
  respondieron: 'var(--color-green)',
  amarillos: 'var(--color-yellow)',
  'rojos nuevos': 'var(--color-red)',
  nuevos: 'var(--color-blue)',
  'te siguen': 'var(--color-blue)',
};

/** The backend's result keys, in plain words. */
const CHIP_LABEL: Record<string, string> = {
  posts: 'posts',
  usuarios: 'personas',
  nuevos: 'personas nuevas',
  'rojos nuevos': 'rojos nuevos',
  salteados: 'posts ya al día (no se pidieron)',
  respondieron: 'te contestaron',
  amarillos: 'nuevos amarillos',
  hilos: 'chats revisados',
  relaciones: '“te sigue” revisados',
  perfiles: 'perfiles nuevos',
  faltan: 'perfiles para la próxima',
  'te siguen': 'te siguen',
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
    <span
      aria-hidden="true"
      className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-blue border-t-transparent"
    />
  );
}

function CloseButton({ onClick, what }: { onClick: () => void; what: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Cerrar aviso: ${what}`}
      title="Cerrar"
      className="-my-1 -mr-1 shrink-0 rounded px-1.5 py-0.5 text-sm text-muted hover:bg-panel-2 hover:text-ink"
    >
      ✕
    </button>
  );
}

function ToastShell({ accent, children }: { accent: string; children: ReactNode }) {
  return (
    <div
      className="anim-toast rounded-xl border border-border bg-panel p-3 shadow-lg"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      {children}
    </div>
  );
}

/** The job's warning: `task.warning`, or an old backend's `result.aviso`. */
function taskWarning(task: Task): string | null {
  if (task.warning) return task.warning;
  const legacy = (task.result as Record<string, unknown>)[LEGACY_WARNING_KEY];
  return typeof legacy === 'string' && legacy ? legacy : null;
}

/** The final numbers, as little pills: bold value + Spanish label. */
function StatChips({ task }: { task: Task }) {
  const result = task.result as Record<string, unknown>;
  const entries = Object.entries(result).filter(
    ([k, v]) => k !== LEGACY_WARNING_KEY && v !== null && v !== undefined && v !== ''
  );
  const warning = taskWarning(task);
  // For scan-like ops with nothing new to show, say so plainly.
  const quiet =
    ['sync', 'refresh', 'scan', 'rescan'].includes(task.kind) &&
    !CHANGE_KEYS.some((k) => Number(result[k]) > 0);

  return (
    <>
      {warning && <p className="mt-1.5 text-xs text-yellow">⚠ {warning}</p>}
      {quiet && <p className="mt-1.5 text-xs text-muted">Sin cambios en el semáforo.</p>}
      {entries.length === 0 ? (
        !quiet && <p className="mt-1 text-xs text-green">Listo.</p>
      ) : (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {entries.map(([k, v]) => (
            <span key={k} className="rounded-md bg-panel-2 px-2 py-0.5 text-xs whitespace-nowrap">
              <b style={{ color: CHIP_COLOR[k] ?? 'var(--color-ink)' }}>
                {v === 'cache' ? 'ya al día' : String(v)}
              </b>{' '}
              <span className="text-muted">{CHIP_LABEL[k] ?? k}</span>
            </span>
          ))}
        </div>
      )}
    </>
  );
}

function TaskToast({ task, onClose }: { task: Task; onClose: () => void }) {
  const meta = kindMeta(task.kind, task.label);
  const pct = task.total > 0 ? Math.round((task.current / task.total) * 100) : null;
  const accent =
    task.status === 'error'
      ? 'var(--color-red)'
      : task.status === 'done'
        ? 'var(--color-green)'
        : 'var(--color-blue)';

  const started = new Date(task.started_at).getTime();
  const elapsed = (task.finished_at ? new Date(task.finished_at).getTime() : Date.now()) - started;
  const state =
    task.status === 'running' ? 'en curso' : task.status === 'done' ? 'terminó' : 'falló';

  return (
    <ToastShell accent={accent}>
      <div className="flex items-center gap-2">
        {task.status === 'running' ? (
          <Spinner />
        ) : task.status === 'done' ? (
          <span aria-hidden="true" className="text-green">
            ✓
          </span>
        ) : (
          <span aria-hidden="true" className="text-red">
            ✕
          </span>
        )}
        <span className="flex-1 truncate text-sm font-semibold">
          {meta.icon} {meta.title}
          <span className="sr-only">: {state}</span>
        </span>
        {/* Live numbers: not announced on every tick (only the outcome is). */}
        <span aria-hidden="true" className="mono shrink-0 text-xs text-muted">
          {task.status === 'running'
            ? task.total > 0
              ? `${task.current} de ${task.total}`
              : fmtDur(elapsed)
            : `en ${fmtDur(elapsed)}`}
        </span>
        <CloseButton onClick={onClose} what={meta.title} />
      </div>

      {task.status === 'running' && task.total > 0 && (
        <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-panel-2">
          <div
            className="h-full rounded-full bg-blue transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {task.status === 'running' && task.message && (
        <p aria-hidden="true" className="mono mt-1.5 truncate text-xs text-muted">
          {task.message}
        </p>
      )}
      {task.status === 'done' && <StatChips task={task} />}
      {task.status === 'error' && <p className="mt-1 text-xs text-red">{task.error}</p>}
    </ToastShell>
  );
}

/** Neutral (not an error): e.g. a job we lost track of, or a finished export. */
function NoticeToast({ notice }: { notice: Notice }) {
  const meta = kindMeta(notice.kind);
  return (
    <ToastShell accent="var(--color-muted)">
      <div className="flex items-center gap-2">
        <span className="block flex-1 truncate text-sm font-semibold">
          {meta.icon} {meta.title}
        </span>
        <CloseButton onClick={() => dismissNotice(notice.id)} what={meta.title} />
      </div>
      <p className="mt-1 text-xs text-muted">{notice.text}</p>
    </ToastShell>
  );
}

function CampaignToast({ c, onClose }: { c: Campaign; onClose: () => void }) {
  const done = c.sent + c.failed;
  const pct = c.total ? Math.round((done / c.total) * 100) : 0;
  const st = campaignStatus(c.status);
  // Rough finish estimate from the remaining sends at the campaign's own pace.
  const eta = c.status === 'running' && c.pending > 0 ? estimateFor(c.pending, c).days : null;
  return (
    <ToastShell accent="var(--color-red)">
      <div className="flex items-center gap-2">
        {c.status === 'running' && <Spinner />}
        <span className="flex-1 truncate text-sm font-semibold">
          ✉ Campaña de DMs · <span className={st.tone}>{st.label}</span>
        </span>
        <span aria-hidden="true" className="mono shrink-0 text-xs text-muted">
          {eta ? `~${eta} día${eta === 1 ? '' : 's'} · ` : ''}
          {c.sent} de {c.total}
        </span>
        <CloseButton onClick={onClose} what="Campaña de DMs" />
      </div>
      <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-panel-2">
        <div className="h-full rounded-full bg-red transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div aria-hidden="true" className="mt-2 flex flex-wrap gap-1.5 text-xs">
        <span className="rounded-md bg-panel-2 px-2 py-0.5">
          <b className="text-green">{c.sent}</b> <span className="text-muted">enviados</span>
        </span>
        {c.failed > 0 && (
          <span className="rounded-md bg-panel-2 px-2 py-0.5">
            <b className="text-red">{c.failed}</b> <span className="text-muted">fallidos</span>
          </span>
        )}
        <span className="rounded-md bg-panel-2 px-2 py-0.5">
          <b className="text-ink">{c.pending}</b> <span className="text-muted">pendientes</span>
        </span>
        <span className="rounded-md bg-panel-2 px-2 py-0.5">
          <b className="text-ink">
            {c.sent_today} de {c.daily_cap}
          </b>{' '}
          <span className="text-muted">hoy</span>
        </span>
      </div>
      {(c.status === 'blocked' || c.status === 'paused') && c.error && (
        <p className={`mt-1.5 text-xs ${c.status === 'blocked' ? 'text-red' : 'text-yellow'}`}>
          {c.error}
        </p>
      )}
    </ToastShell>
  );
}

export function Toasts() {
  const qc = useQueryClient();
  const active = useIsMutating() > 0;
  const streaming = useTaskStream(); // pushed by the server; polling only as fallback
  const tasks = useTasks(active, streaming);
  const campaign = useActiveCampaign(active);
  const notices = useNotices();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // Failed tasks are kept here so their toast stays after the backend drops
  // them from /tasks (it prunes finished tasks), until the user closes it.
  const [failed, setFailed] = useState<Task[]>([]);
  const processed = useRef<Set<string>>(new Set());

  const dismiss = (key: string) => setDismissed((s) => new Set(s).add(key));

  useEffect(() => {
    for (const t of tasks.data ?? []) {
      if ((t.status === 'done' || t.status === 'error') && !processed.current.has(t.id)) {
        processed.current.add(t.id);
        if (t.status === 'done') {
          // Refresh only what this kind of task changed.
          refreshAfterJob(qc, t.kind);
          const id = t.id;
          setTimeout(() => setDismissed((s) => new Set(s).add(id)), DONE_SHOW_MS);
        } else {
          setFailed((f) => [...f, t]);
        }
      }
    }
  }, [tasks.data, qc]);

  const live = (tasks.data ?? []).filter((t) => t.status !== 'error' && !dismissed.has(t.id));
  const errors = failed.filter((t) => !dismissed.has(t.id));
  const camp = campaign.data;
  // Keyed by status too: closing it hides this state, a new state shows again.
  const campKey = camp ? `campaign:${camp.id}:${camp.status}` : '';
  const showCamp = camp != null && camp.status !== 'done' && !dismissed.has(campKey);

  // The two live regions are always mounted, so screen readers hear what
  // appears in them: errors right away (alert), the rest politely (status).
  return (
    <div className="fixed right-4 bottom-4 z-40 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      <div role="alert" className="flex flex-col gap-2">
        {errors.map((t) => (
          <TaskToast key={t.id} task={t} onClose={() => dismiss(t.id)} />
        ))}
      </div>
      <div role="status" aria-live="polite" className="flex flex-col gap-2">
        {showCamp && camp && <CampaignToast c={camp} onClose={() => dismiss(campKey)} />}
        {live.map((t) => (
          <TaskToast key={t.id} task={t} onClose={() => dismiss(t.id)} />
        ))}
        {notices.map((n) => (
          <NoticeToast key={n.id} notice={n} />
        ))}
      </div>
    </div>
  );
}
