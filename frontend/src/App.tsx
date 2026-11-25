import { useEffect, useMemo, useState } from 'react';
import { ApiError, type ExportQuery, type Order, type TrafficLight } from './api/client';
import { useCounts, useEvents, useStatus } from './api/hooks';
import { ActionsMenu } from './components/ActionsMenu';
import { ActivityPage } from './components/ActivityPage';
import { Board } from './components/board/Board';
import { CampaignModal } from './components/campaign/CampaignModal';
import { ExportButtons } from './components/board/ExportButtons';
import { Cursor } from './components/ui/Cursor';
import { ErrorBanner } from './components/ui/ErrorBanner';
import { FiestaModal } from './components/FiestaModal';
import { FilterBar } from './components/board/FilterBar';
import { GettingStarted } from './components/board/GettingStarted';
import { HelpPage } from './components/HelpPage';
import { Navbar, type Page } from './components/Navbar';
import { PostsDrawer } from './components/PostsDrawer';
import { ScanBar } from './components/ScanBar';
import { Toasts } from './components/Toasts';
import { UsersTable } from './components/board/UsersTable';
import { describeFilters, type ActiveFilters } from './lib/filters';
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
  const dataStatus = useStatus(); // shared with Actualizar ▾ (one local read)
  const follows = onlyFollowers || undefined;
  // Debounced so the derived queries (counts + users) only refetch once typing
  // pauses, instead of on every keystroke.
  const debouncedSearch = useDebouncedValue(search);
  const searchQ = debouncedSearch || undefined;
  const counts = useCounts({ event, search: searchQ, follows });
  const c = counts.data ?? { red: 0, yellow: 0, green: 0, total: 0 };

  const selected = useMemo(() => events.data?.find((e) => e.id === event), [events.data, event]);

  // If the selected fiesta vanished (e.g. after "Borrar todo"), drop back to
  // "Todas las fiestas" so the UI doesn't scope queries to a dead id or show
  // "undefined" as the event name.
  useEffect(() => {
    if (event !== undefined && events.data && !events.data.some((e) => e.id === event)) {
      setEvent(undefined);
    }
  }, [events.data, event]);
  const contacted = c.yellow + c.green;
  const pct = c.total ? Math.round((contacted / c.total) * 100) : 0;
  const tableTotal = status ? c[status] : c.total;
  const fiestas = events.data ?? [];
  const hasPosts = selected ? selected.posts_count > 0 : fiestas.some((e) => e.posts_count > 0);
  // The filters on top of the fiesta (the table's color picker only counts there).
  const filters: ActiveFilters = {
    search: searchQ,
    onlyFollowers,
    status: view === 'table' ? status || undefined : undefined,
  };
  const clearFilters = () => {
    setSearch('');
    setOnlyFollowers(false);
    setStatus('');
  };
  // The export mirrors the visible view: the Board is its three color columns
  // (no status filter); the Table applies the status picker.
  const exportQuery: ExportQuery =
    view === 'board'
      ? { event, search: searchQ, order, follows, by_status: true }
      : { event, status: status || undefined, search: searchQ, order, follows };

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
          {/* Row 1 — the fiesta: drives the filter, where scans go and the counts */}
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={event ?? ''}
              onChange={(e) => setEvent(e.target.value ? Number(e.target.value) : undefined)}
              aria-label="Elegir fiesta"
              className="rounded-lg border border-border bg-panel px-3 py-1.5 text-sm font-medium outline-none"
            >
              <option value="">Todas las fiestas</option>
              {fiestas.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} ({e.posts_count} post{e.posts_count === 1 ? '' : 's'})
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setShowFiesta(true)}
              className="rounded-lg bg-panel-2 px-3 py-1.5 text-sm font-medium hover:bg-border"
            >
              + Nueva fiesta
            </button>
            {selected && (
              <>
                <span className="text-xs text-muted">
                  Promo desde {fmtDate(selected.promo_start)} · fiesta{' '}
                  {fmtDate(selected.event_date)}{' '}
                  {new Date(selected.event_date) < new Date() ? '(ya pasó)' : '(próxima)'}
                </span>
                <div
                  className="flex min-w-[220px] flex-1 items-center gap-2"
                  title="🟡 + 🟢: a los que ya les escribiste"
                >
                  <div
                    role="progressbar"
                    aria-label="Contactados"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={pct}
                    className="h-2 flex-1 overflow-hidden rounded-full bg-panel-2"
                  >
                    <div className="h-full rounded-full bg-green" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="shrink-0 text-xs text-muted">
                    Contactados {contacted} de {c.total} ({pct}%)
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Row 2 — what you can do with it */}
          <div className="flex flex-wrap items-center gap-3">
            <ActionsMenu
              event={event}
              lastScannedAt={selected?.last_scanned_at}
              primary={hasPosts}
              onError={setError}
            />
            <button
              type="button"
              onClick={() => setShowCampaign(true)}
              disabled={!selected}
              title={
                selected
                  ? 'Mandar un mensaje a los rojos de la fiesta, lento y con cuidado'
                  : 'Elegí una fiesta para armar una campaña'
              }
              className="rounded-lg border border-red/60 px-3 py-1.5 text-sm font-semibold text-red hover:bg-red/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
            >
              ✉ Campaña de DMs
            </button>
            {!selected && (
              <span className="text-xs text-muted">Elegí una fiesta para armar una campaña.</span>
            )}
          </div>

          <ScanBar
            event={event}
            eventName={selected?.name}
            primary={!hasPosts}
            onError={setError}
          />

          <ErrorBanner error={error} onClose={() => setError(null)} />

          {events.data && dataStatus.data && (
            <GettingStarted
              hasFiesta={fiestas.length > 0}
              hasPosts={fiestas.some((e) => e.posts_count > 0)}
              dmsSynced={dataStatus.data.dms_synced_at != null}
            />
          )}

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
          >
            <ExportButtons
              query={exportQuery}
              count={view === 'board' ? c.total : tableTotal}
              scope={selected?.name ?? 'Todas las fiestas'}
              filters={describeFilters(filters)}
              onError={setError}
            />
          </FilterBar>

          {showPosts && <PostsDrawer event={event} onError={setError} />}

          <main className="flex-1">
            {counts.isError ? (
              <p role="alert" className="py-12 text-center text-sm text-red">
                No se pudo conectar con la app. Cerrala y abrila de nuevo.
              </p>
            ) : counts.isPending ? (
              <p className="py-12 text-center text-sm text-muted">Cargando…</p>
            ) : view === 'board' ? (
              <Board
                event={event}
                search={searchQ}
                order={order}
                follows={follows}
                counts={{ red: c.red, yellow: c.yellow, green: c.green }}
                filters={filters}
                onClearFilters={clearFilters}
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
                filters={filters}
                onClearFilters={clearFilters}
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
      <Cursor />
    </>
  );
}
