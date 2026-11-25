import type { ReactNode } from 'react';
import type { Order, TrafficLight } from '../../api/client';
import { INPUT_CLS } from '../../lib/ui';
import { LIGHTS, LIGHT_LABEL } from '../../lib/user';

type View = 'board' | 'table';

/** The board/table toolbar: view toggle, search, status (table only), order,
 * follower filter, posts drawer toggle, plus trailing actions (`children`, e.g.
 * the export buttons). Pure controlled component — App owns the state. */
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
  children,
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
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label="Cómo ver la lista"
        className="flex overflow-hidden rounded-lg border border-border"
      >
        {(['board', 'table'] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => onView(v)}
            aria-pressed={view === v}
            className={`px-3 py-1.5 text-sm font-medium ${
              view === v ? 'bg-panel-2 text-ink' : 'text-muted hover:text-ink'
            }`}
          >
            {v === 'board' ? 'Tarjetas' : 'Tabla'}
          </button>
        ))}
      </div>

      <input
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        type="search"
        placeholder="Buscar @usuario o nombre…"
        aria-label="Buscar por @usuario o nombre"
        className={`${INPUT_CLS} placeholder:text-muted`}
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
        <option value="status">Orden: color del semáforo</option>
        <option value="fans">Orden: más interacciones 🔥</option>
        <option value="followers">Orden: más seguidores</option>
        <option value="username">Orden: @usuario (A-Z)</option>
      </select>

      <button
        type="button"
        onClick={onToggleFollowers}
        aria-pressed={onlyFollowers}
        title="Mostrar solo los que te siguen (más seguros para escribir)"
        className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${
          onlyFollowers
            ? 'border-blue bg-blue/15 text-blue'
            : 'border-border text-muted hover:text-ink'
        }`}
      >
        {onlyFollowers ? '✓ Solo seguidores' : 'Solo seguidores'}
      </button>

      <button
        type="button"
        onClick={onTogglePosts}
        aria-expanded={showPosts}
        className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-panel"
      >
        {showPosts ? 'Ocultar posts' : 'Ver posts'}
      </button>

      {children}
    </div>
  );
}
