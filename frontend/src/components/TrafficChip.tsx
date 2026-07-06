import type { TrafficLight } from '../api/client';
import { LIGHT_LABEL } from '../lib/user';

const DOT: Record<TrafficLight, string> = {
  red: 'bg-red text-red',
  yellow: 'bg-yellow text-yellow',
  green: 'bg-green text-green',
};

export function TrafficDot({ light }: { light: TrafficLight }) {
  return <span className={`dot-glow inline-block h-2.5 w-2.5 rounded-full ${DOT[light]}`} />;
}

export function TrafficChip({ light }: { light: TrafficLight }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted">
      <TrafficDot light={light} />
      {LIGHT_LABEL[light]}
    </span>
  );
}
