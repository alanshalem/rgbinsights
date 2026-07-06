import type { Order, TrafficLight } from '../api/client';
import { INPUT_CLS } from '../lib/ui';
import { LIGHTS, LIGHT_LABEL } from '../lib/user';

type View = 'board' | 'table';

/** The board/table toolbar: view toggle, search, status (table only), order,
 * follower filter, posts drawer toggle. Pure controlled component — App owns
 * the state. */
export function FilterBar({
  view,
  onView,
  search,
  onSearch,
  status,
  onStatus,
  order,
  onOrder,
  onlyFollowers,
  onToggleFollowers,
  showPosts,
  onTogglePosts,
}: {
  view: View;
  onView: (v: View) => void;
  search: string;
  onSearch: (s: string) => void;
  status: TrafficLight | '';
  onStatus: (s: TrafficLight | '') => void;
  order: Order;
  onOrder: (o: Order) => void;
  onlyFollowers: boolean;
  onToggleFollowers: () => void;
  showPosts: boolean;
  onTogglePosts: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex overflow-hidden rounded-lg border border-[var(--color-border)]">
        {(['board', 'table'] as const).map((v) => (
          <button
            key={v}
            onClick={() => onView(v)}
            aria-pressed={view === v}
            className={`px-3 py-1.5 text-sm font-medium ${
              view === v
                ? 'bg-[var(--color-panel-2)] text-[var(--color-ink)]'
                : 'text-[var(--color-muted)] hover:text-[var(--color-ink)]'
            }`}
          >
            {v === 'board' ? 'Board' : 'Tabla'}
          </button>
        ))}
      </div>

      <input
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        placeholder="Buscar @usuario o nombre…"
        aria-label="Buscar usuario"
        className={`${INPUT_CLS} placeholder:text-[var(--color-muted)]`}
      />

      {view === 'table' && (
        <select
          value={status}
          onChange={(e) => onStatus(e.target.value as TrafficLight | '')}
          aria-label="Filtrar por estado"
          className={INPUT_CLS}
        >
          <option value="">Todos los estados</option>
          {LIGHTS.map((l) => (
            <option key={l} value={l}>
              {LIGHT_LABEL[l]}
            </option>
          ))}
        </select>
      )}

      <select
        value={order}
        onChange={(e) => onOrder(e.target.value as Order)}
        aria-label="Ordenar por"
        className={INPUT_CLS}
      >
        <option value="status">Orden: estado</option>
        <option value="fans">Orden: fans 🔥</option>
        <option value="followers">Orden: seguidores 🌟</option>
        <option value="username">Orden: usuario</option>
      </select>

      <button
        onClick={onToggleFollowers}
        aria-pressed={onlyFollowers}
        title="Mostrar solo los que te siguen (más seguros para escribir)"
        className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${
          onlyFollowers
            ? 'border-[var(--color-blue)] bg-[var(--color-blue)]/15 text-[var(--color-blue)]'
            : 'border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-ink)]'
        }`}
      >
        {onlyFollowers ? '✓ Solo seguidores' : 'Solo seguidores'}
      </button>

      <button
        onClick={onTogglePosts}
        className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-sm hover:bg-[var(--color-panel)]"
      >
        {showPosts ? 'Ocultar posts' : 'Ver posts'}
      </button>
    </div>
  );
}
