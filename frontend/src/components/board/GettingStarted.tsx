import type { ReactNode } from 'react';
import { JOB_META } from '../../lib/jobs';

function Step({ n, done, children }: { n: number; done: boolean; children: ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span
        aria-hidden="true"
        className={`mono mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
          done ? 'bg-green text-bg' : 'border border-border text-muted'
        }`}
      >
        {done ? '✓' : n}
      </span>
      <span className={done ? 'text-muted line-through' : 'text-ink'}>
        <span className="sr-only">{done ? 'Hecho: ' : 'Pendiente: '}</span>
        {children}
      </span>
    </li>
  );
}

/** First-run guide: the three steps to a useful semáforo, each ticked from data
 * the app already has locally (fiestas, their posts, the last DM sync). It never
 * starts anything by itself, and it goes away once the three are done. */
export function GettingStarted({
  hasFiesta,
  hasPosts,
  dmsSynced,
}: {
  hasFiesta: boolean;
  hasPosts: boolean;
  dmsSynced: boolean;
}) {
  if (hasFiesta && hasPosts && dmsSynced) return null;
  return (
    <section
      aria-labelledby="getting-started"
      className="rounded-2xl border border-blue/40 bg-blue/5 p-4"
    >
      <h2
        id="getting-started"
        className="display mb-2 text-base font-black tracking-tight uppercase"
      >
        Cómo empezar
      </h2>
      <ol className="flex flex-col gap-1.5 text-sm">
        <Step n={1} done={hasFiesta}>
          Creá una fiesta con <b>+ Nueva fiesta</b>.
        </Step>
        <Step n={2} done={hasPosts}>
          Pegá los links de sus posts y tocá <b>Escanear</b>: aparece la gente que comentó o likeó.
        </Step>
        <Step n={3} done={dmsSynced}>
          <b>Actualizar ▾ → {JOB_META.sync.title}</b>: pinta a cada uno de 🔴, 🟡 o 🟢 según sus
          DMs.
        </Step>
      </ol>
    </section>
  );
}
