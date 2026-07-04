import type { TrafficLight } from '../api/client';
import { LIGHT_LABEL, LIGHTS } from '../lib/user';
import { TrafficDot } from './TrafficChip';

export function Navbar({
  counts,
  onManual,
}: {
  counts: Record<TrafficLight, number>;
  onManual: () => void;
}) {
  return (
    <nav className="sticky top-0 z-30 border-b border-[var(--color-border)] bg-[var(--color-bg)]/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2.5 md:px-6">
        <div className="flex items-center gap-3">
          <img src="/logo.png" alt="RGB Collective" className="h-9 w-auto md:h-11" />
          <span className="hidden text-xs text-[var(--color-muted)] sm:block">
            Outreach por DM · @rgb.collective___
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex gap-3 text-sm">
            {LIGHTS.map((l) => (
              <div key={l} className="flex items-center gap-1.5">
                <TrafficDot light={l} />
                <span className="mono font-semibold">{counts[l]}</span>
                <span className="hidden text-[var(--color-muted)] sm:inline">{LIGHT_LABEL[l]}</span>
              </div>
            ))}
          </div>
          <button
            onClick={onManual}
            className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--color-panel)]"
          >
            Ayuda
          </button>
        </div>
      </div>
    </nav>
  );
}
