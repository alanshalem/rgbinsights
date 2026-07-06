import { useMemo, useState } from 'react';
import { ApiError, type Order, type TrafficLight } from './api/client';
import { useCounts, useEvents } from './api/hooks';
import { ActionsMenu } from './components/ActionsMenu';
import { ActivityPage } from './components/ActivityPage';
import { Board } from './components/Board';
import { CampaignModal } from './components/CampaignModal';
import { ErrorBanner } from './components/ErrorBanner';
import { FiestaModal } from './components/FiestaModal';
import { FilterBar } from './components/FilterBar';
import { HelpPage } from './components/HelpPage';
import { Navbar, type Page } from './components/Navbar';
import { PostsDrawer } from './components/PostsDrawer';
import { ScanBar } from './components/ScanBar';
import { Toasts } from './components/Toasts';
import { UsersTable } from './components/UsersTable';
import { useDebouncedValue } from './lib/useDebouncedValue';

type View = 'board' | 'table';

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('es-AR', { day: '2-digit', month: 'short' });
}

export default function App() {
  const [page, setPage] = useState<Page>('app');
  const [view, setView] = useState<View>('board');
  const [event, setEvent] = useState<number | undefined>(undefined);
  const [status, setStatus] = useState<TrafficLight | ''>('');
  const [search, setSearch] = useState('');
  const [order, setOrder] = useState<Order>('status');
  const [onlyFollowers, setOnlyFollowers] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [showFiesta, setShowFiesta] = useState(false);
  const [showPosts, setShowPosts] = useState(false);
  const [showCampaign, setShowCampaign] = useState(false);

  const events = useEvents();
  const follows = onlyFollowers || undefined;
  // Debounced so the derived queries (counts + users) only refetch once typing
  // pauses, instead of on every keystroke.
  const debouncedSearch = useDebouncedValue(search);
  const searchQ = debouncedSearch || undefined;
  const counts = useCounts({ event, search: searchQ, follows });
  const c = counts.data ?? { red: 0, yellow: 0, green: 0, total: 0 };

  const selected = useMemo(() => events.data?.find((e) => e.id === event), [events.data, event]);
  const contacted = c.yellow + c.green;
  const pct = c.total ? Math.round((contacted / c.total) * 100) : 0;
  const tableTotal = status ? c[status] : c.total;

  return (
    <>
      <Navbar
        counts={{ red: c.red, yellow: c.yellow, green: c.green }}
        page={page}
        onNav={setPage}
      />

      {page === 'help' ? (
        <HelpPage onBack={() => setPage('app')} />
      ) : page === 'activity' ? (
        <ActivityPage onBack={() => setPage('app')} />
      ) : (
        <div className="mx-auto flex min-h-full max-w-7xl flex-col gap-4 p-4 md:p-6">
          {/* Fiesta context: drives filter + scan target + counts */}
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={event ?? ''}
              onChange={(e) => setEvent(e.target.value ? Number(e.target.value) : undefined)}
              aria-label="Elegir fiesta"
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm font-medium outline-none"
            >
              <option value="">Todas las fiestas</option>
              {(events.data ?? []).map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} ({e.posts_count})
                </option>
              ))}
            </select>
            <button
              onClick={() => setShowFiesta(true)}
              className="rounded-lg bg-[var(--color-panel-2)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--color-border)]"
            >
              + Nueva fiesta
            </button>
            <ActionsMenu
              event={event}
              lastScannedAt={selected?.last_scanned_at}
              onError={setError}
            />
            {selected && (
              <>
                <button
                  onClick={() => setShowCampaign(true)}
                  title="Enviar un mensaje a los rojos de la fiesta, con envío lento y seguro"
                  className="rounded-lg border border-[var(--color-red)]/60 px-3 py-1.5 text-sm font-semibold text-[var(--color-red)] hover:bg-[var(--color-red)]/10"
                >
                  ✉ Campaña de DMs
                </button>
                <span className="mono text-xs text-[var(--color-muted)]">
                  campaña {fmtDate(selected.promo_start)} → evento {fmtDate(selected.event_date)}{' '}
                  {new Date(selected.event_date) < new Date() ? '· ya pasó' : '· próxima'}
                </span>
                <div className="flex min-w-[180px] flex-1 items-center gap-2">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--color-panel-2)]">
                    <div
                      className="h-full rounded-full bg-[var(--color-green)]"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="mono shrink-0 text-xs text-[var(--color-muted)]">
                    contactaste {contacted}/{c.total}
                  </span>
                </div>
              </>
            )}
          </div>

          <ScanBar event={event} eventName={selected?.name} onError={setError} />

          <ErrorBanner error={error} />

          <FilterBar
            view={view}
            onView={setView}
            search={search}
            onSearch={setSearch}
            status={status}
            onStatus={setStatus}
            order={order}
            onOrder={setOrder}
            onlyFollowers={onlyFollowers}
            onToggleFollowers={() => setOnlyFollowers((v) => !v)}
            showPosts={showPosts}
            onTogglePosts={() => setShowPosts((s) => !s)}
          />

          {showPosts && <PostsDrawer event={event} onError={setError} />}

          <main className="flex-1">
            {counts.isError ? (
              <p className="py-12 text-center text-sm text-[var(--color-red)]">
                No se pudo cargar. ¿Está corriendo el backend en :8000?
              </p>
            ) : view === 'board' ? (
              <Board
                event={event}
                search={searchQ}
                order={order}
                follows={follows}
                counts={{ red: c.red, yellow: c.yellow, green: c.green }}
              />
            ) : (
              <UsersTable
                query={{
                  event,
                  status: status || undefined,
                  search: searchQ,
                  order,
                  follows,
                }}
                total={tableTotal}
              />
            )}
          </main>
        </div>
      )}

      {showFiesta && (
        <FiestaModal
          onClose={() => setShowFiesta(false)}
          onCreated={(id) => {
            setEvent(id);
            setShowFiesta(false);
          }}
        />
      )}
      {showCampaign && selected && (
        <CampaignModal
          event={selected.id}
          eventName={selected.name}
          onClose={() => setShowCampaign(false)}
        />
      )}
      <Toasts />
    </>
  );
}
