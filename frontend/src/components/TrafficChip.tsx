import type { TrafficLight } from '../api/client';
import { LIGHT_LABEL } from '../lib/user';

const DOT: Record<TrafficLight, string> = {
  red: 'bg-[var(--color-red)]',
  yellow: 'bg-[var(--color-yellow)]',
  green: 'bg-[var(--color-green)]',
};

export function TrafficDot({ light }: { light: TrafficLight }) {
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${DOT[light]}`} />;
}

export function TrafficChip({ light }: { light: TrafficLight }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-muted)]">
      <TrafficDot light={light} />
      {LIGHT_LABEL[light]}
    </span>
  );
}
