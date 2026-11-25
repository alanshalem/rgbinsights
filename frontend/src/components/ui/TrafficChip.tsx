import type { TrafficLight } from '../../api/client';
import { LIGHT_HINT, LIGHT_LABEL, LIGHTS } from '../../lib/user';

const DOT: Record<TrafficLight, string> = {
  red: 'bg-red text-red',
  yellow: 'bg-yellow text-yellow',
  green: 'bg-green text-green',
};

/** Decorative: always shown next to the color's name or an aria-label. */
export function TrafficDot({ light }: { light: TrafficLight }) {
  return (
    <span
      aria-hidden="true"
      className={`dot-glow inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT[light]}`}
    />
  );
}

export function TrafficChip({ light }: { light: TrafficLight }) {
  return (
    <span
      title={LIGHT_HINT[light]}
      className="inline-flex items-center gap-1.5 text-xs font-medium text-muted"
    >
      <TrafficDot light={light} />
      {LIGHT_LABEL[light]}
    </span>
  );
}

/** One line that says what the three colors mean. */
export function TrafficLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      {LIGHTS.map((l) => (
        <span key={l} className="inline-flex items-center gap-1.5">
          <TrafficDot light={l} />
          <b className="font-semibold text-ink">{LIGHT_LABEL[l]}:</b> {LIGHT_HINT[l].toLowerCase()}
        </span>
      ))}
    </p>
  );
}
