import { useMemo } from 'react';
import type { Order, TrafficLight, UserOut } from '../../api/client';
import { useUserPages } from '../../api/hooks';
import { hasFilters, type ActiveFilters } from '../../lib/filters';
import { LIGHT_HINT, LIGHT_LABEL } from '../../lib/user';
import { NoResults } from './NoResults';
import { UserCard } from './UserCard';

const PAGE = 20;

const ACCENT: Record<TrafficLight, string> = {
  red: 'var(--color-red)',
  yellow: 'var(--color-yellow)',
  green: 'var(--color-green)',
};

type ColumnQuery = { event?: number; search?: string; order: Order; follows?: boolean };

/** Flatten the loaded pages, dropping a repeat that an offset shift (data changed
 * between two page fetches) could bring in, so cards and keys stay unique. */
function uniqueRows(pages: UserOut[][] | undefined): UserOut[] {
  const seen = new Set<string>();
  const rows: UserOut[] = [];
  for (const u of pages?.flat() ?? []) {
    if (seen.has(u.pk)) continue;
    seen.add(u.pk);
    rows.push(u);
  }
  return rows;
}

function Column({
  light,
  total,
  query,
  filtered,
}: {
  light: TrafficLight;
  total: number;
  query: ColumnQuery;
  filtered: boolean;
}) {
  const users = useUserPages({ ...query, status: light }, PAGE);
  const rows = useMemo(() => uniqueRows(users.data?.pages), [users.data]);

  return (
    <section className="anim-fade-up flex min-w-0 flex-1 flex-col rounded-2xl border border-border bg-panel/40">
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
              className="dot-glow anim-dot-pulse h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: ACCENT[light], color: ACCENT[light] }}
            />
            <h2 className="display text-lg font-black tracking-tight uppercase">
              {LIGHT_LABEL[light]}
            </h2>
          </div>
          <span className="mono text-sm text-muted" aria-label={`${total} personas`}>
            {total}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-muted">{LIGHT_HINT[light]}</p>
      </header>
      <div className="flex flex-col gap-2.5 overflow-y-auto p-3">
        {total === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            {filtered
              ? `Nadie en ${LIGHT_LABEL[light]} con estos filtros`
              : `Nadie en ${LIGHT_LABEL[light]} todavía`}
          </p>
        ) : (
          rows.map((u) => <UserCard key={u.pk} user={u} />)
        )}
        {/* Only when there IS a next page: `total` comes from another query, so
            rows < total with no next page (data changed meanwhile) would be a
            dead button. */}
        {users.hasNextPage && rows.length < total && (
          <button
            type="button"
            onClick={() => {
              // Only the next page; a click while it loads would just repeat it.
              if (!users.isFetchingNextPage) void users.fetchNextPage();
            }}
            className="rounded-lg border border-border py-1.5 text-sm text-muted hover:text-ink"
          >
            {users.isFetchingNextPage ? 'Cargando…' : `Cargar más (${rows.length} de ${total})`}
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
  filters,
  onClearFilters,
}: {
  event?: number;
  search?: string;
  order: Order;
  follows?: boolean;
  counts: Record<TrafficLight, number>;
  filters: ActiveFilters;
  onClearFilters: () => void;
}) {
  const query: ColumnQuery = { event, search, order, follows };
  const filtered = hasFilters(filters);
  // Filters that hide everyone: one clear message instead of three empty columns.
  if (filtered && counts.red + counts.yellow + counts.green === 0) {
    return <NoResults filters={filters} onClear={onClearFilters} />;
  }
  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start">
      {(['red', 'yellow', 'green'] as const).map((light) => (
        <Column key={light} light={light} total={counts[light]} query={query} filtered={filtered} />
      ))}
    </div>
  );
}
