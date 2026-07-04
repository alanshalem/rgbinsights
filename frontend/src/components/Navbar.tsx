import type { TrafficLight } from '../api/client';
import { LIGHT_LABEL, LIGHTS } from '../lib/user';
import { IgSession } from './IgSession';
import { TrafficDot } from './TrafficChip';

export type Page = 'app' | 'activity' | 'help';

const NAV: { page: Page; label: string }[] = [
  { page: 'app', label: 'Panel' },
  { page: 'activity', label: 'Actividad' },
  { page: 'help', label: 'Ayuda' },
];

export function Navbar({
  counts,
  page,
  onNav,
}: {
  counts: Record<TrafficLight, number>;
  page: Page;
  onNav: (p: Page) => void;
}) {
  return (
    <nav className="sticky top-0 z-30 border-b border-[var(--color-border)] bg-[var(--color-bg)]/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2.5 md:px-6">
        <button onClick={() => onNav('app')} className="flex items-center gap-3">
          <img src="/logo.png" alt="RGB Collective" className="h-12 w-auto md:h-16" />
        </button>
        <div className="flex items-center gap-4">
          <IgSession />
          {page === 'app' && (
            <div className="hidden gap-3 text-sm sm:flex">
              {LIGHTS.map((l) => (
                <div key={l} className="flex items-center gap-1.5">
                  <TrafficDot light={l} />
                  <span className="mono font-semibold">{counts[l]}</span>
                  <span className="hidden text-[var(--color-muted)] md:inline">
                    {LIGHT_LABEL[l]}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="flex overflow-hidden rounded-lg border border-[var(--color-border)]">
            {NAV.map((n) => (
              <button
                key={n.page}
                onClick={() => onNav(n.page)}
                className={`px-3 py-1.5 text-sm font-medium ${
                  page === n.page
                    ? 'bg-[var(--color-panel-2)] text-[var(--color-ink)]'
                    : 'text-[var(--color-muted)] hover:text-[var(--color-ink)]'
                }`}
              >
                {n.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
}
