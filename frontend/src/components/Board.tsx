import { useState } from 'react';
import type { Order, TrafficLight } from '../api/client';
import { useUsers } from '../api/hooks';
import { LIGHT_HINT, LIGHT_LABEL } from '../lib/user';
import { UserCard } from './UserCard';

const PAGE = 20;

const ACCENT: Record<TrafficLight, string> = {
  red: 'var(--color-red)',
  yellow: 'var(--color-yellow)',
  green: 'var(--color-green)',
};

type ColumnQuery = { event?: number; search?: string; order: Order; follows?: boolean };

function Column({
  light,
  total,
  query,
}: {
  light: TrafficLight;
  total: number;
  query: ColumnQuery;
}) {
  const [pages, setPages] = useState(1);
  const limit = pages * PAGE;
  const users = useUsers({ ...query, status: light, limit, offset: 0 });
  const rows = users.data ?? [];

  return (
    <section className="flex min-w-0 flex-1 flex-col rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)]/40">
      <header
        className="rounded-t-2xl border-t-2 px-4 py-3"
        style={{
          borderTopColor: ACCENT[light],
          background: `linear-gradient(to bottom, color-mix(in srgb, ${ACCENT[light]} 12%, transparent), transparent)`,
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: ACCENT[light], boxShadow: `0 0 9px ${ACCENT[light]}` }}
            />
            <h2 className="display text-lg font-black tracking-tight uppercase">
              {LIGHT_LABEL[light]}
            </h2>
          </div>
          <span className="mono text-sm text-[var(--color-muted)]">{total}</span>
        </div>
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">{LIGHT_HINT[light]}</p>
      </header>
      <div className="flex flex-col gap-2.5 overflow-y-auto p-3">
        {total === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--color-muted)]">—</p>
        ) : (
          rows.map((u) => <UserCard key={u.pk} user={u} />)
        )}
        {rows.length < total && (
          <button
            onClick={() => setPages((p) => p + 1)}
            className="rounded-lg border border-[var(--color-border)] py-1.5 text-sm text-[var(--color-muted)] hover:text-[var(--color-ink)]"
          >
            Cargar más ({rows.length}/{total})
          </button>
        )}
      </div>
    </section>
  );
}

export function Board({
  event,
  search,
  order,
  follows,
  counts,
}: {
  event?: number;
  search?: string;
  order: Order;
  follows?: boolean;
  counts: Record<TrafficLight, number>;
}) {
  const query: ColumnQuery = { event, search, order, follows };
  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start">
      {(['red', 'yellow', 'green'] as const).map((light) => (
        <Column key={light} light={light} total={counts[light]} query={query} />
      ))}
    </div>
  );
}
