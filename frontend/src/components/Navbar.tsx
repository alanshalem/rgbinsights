import type { TrafficLight } from '../api/client';
import { LIGHT_HINT, LIGHT_LABEL, LIGHTS } from '../lib/user';
import { IgSession } from './ig/IgSession';
import { TrafficDot } from './ui/TrafficChip';

export type Page = 'app' | 'activity' | 'config' | 'help';

const NAV: { page: Page; label: string }[] = [
  { page: 'app', label: 'Panel' },
  { page: 'activity', label: 'Actividad' },
  { page: 'config', label: 'Configuración' },
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
    <nav
      aria-label="Principal"
      className="sticky top-0 z-30 border-b border-border bg-bg/80 backdrop-blur"
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2.5 md:px-6">
        <button
          type="button"
          onClick={() => onNav('app')}
          aria-label="RGB Collective · ir al panel"
          className="flex items-center gap-3"
        >
          <img src="/logo.png" alt="" className="h-12 w-auto md:h-16" />
        </button>
        <div className="flex items-center gap-4">
          <IgSession />
          {page === 'app' && (
            <ul aria-label="Cuántos hay de cada color" className="hidden gap-3 text-sm sm:flex">
              {LIGHTS.map((l) => (
                <li
                  key={l}
                  title={`${LIGHT_LABEL[l]}: ${LIGHT_HINT[l]}`}
                  aria-label={`${counts[l]} en ${LIGHT_LABEL[l]}: ${LIGHT_HINT[l]}`}
                  className="flex items-center gap-1.5"
                >
                  <TrafficDot light={l} />
                  <span aria-hidden="true" className="mono font-semibold">
                    {counts[l]}
                  </span>
                  <span aria-hidden="true" className="hidden text-muted md:inline">
                    {LIGHT_LABEL[l]}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="flex overflow-hidden rounded-lg border border-border">
            {NAV.map((n) => (
              <button
                type="button"
                key={n.page}
                onClick={() => onNav(n.page)}
                aria-current={page === n.page ? 'page' : undefined}
                className={`px-3 py-1.5 text-sm font-medium ${
                  page === n.page ? 'bg-panel-2 text-ink' : 'text-muted hover:text-ink'
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
