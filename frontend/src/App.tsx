import { useMemo, useState } from 'react';
import { ApiError, type Order, type TrafficLight } from './api/client';
import { useCounts, useEvents } from './api/hooks';
import { ActionsMenu } from './components/ActionsMenu';
import { ActivityPage } from './components/ActivityPage';
import { Board } from './components/Board';
import { CampaignModal } from './components/CampaignModal';
import { FiestaModal } from './components/FiestaModal';
import { HelpPage } from './components/HelpPage';
import { Navbar, type Page } from './components/Navbar';
import { PostsDrawer } from './components/PostsDrawer';
import { ScanBar } from './components/ScanBar';
import { Toasts } from './components/Toasts';
import { UsersTable } from './components/UsersTable';
import { LIGHTS, LIGHT_LABEL } from './lib/user';

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
  const counts = useCounts({ event, search: search || undefined, follows });
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
            <ActionsMenu event={event} onError={setError} />
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

          {error && (
            <div
              className={`rounded-xl border px-4 py-3 text-sm ${
                error.isChallenge
                  ? 'border-[var(--color-yellow)]/50 bg-[var(--color-yellow)]/10 text-[var(--color-yellow)]'
                  : 'border-[var(--color-red)]/50 bg-[var(--color-red)]/10 text-[var(--color-red)]'
              }`}
            >
              {error.isChallenge ? (
                <>
                  <strong>Instagram pide verificación.</strong> La sesión del navegador se venció:
                  corré <code>python -m app.login_browser</code> y reintentá. {error.message}
                </>
              ) : (
                <>Error: {error.message}</>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex overflow-hidden rounded-lg border border-[var(--color-border)]">
              {(['board', 'table'] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
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
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar @usuario o nombre…"
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm outline-none placeholder:text-[var(--color-muted)]"
            />

            {view === 'table' && (
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as TrafficLight | '')}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm outline-none"
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
              onChange={(e) => setOrder(e.target.value as Order)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm outline-none"
            >
              <option value="status">Orden: estado</option>
              <option value="fans">Orden: fans 🔥</option>
              <option value="followers">Orden: seguidores 🌟</option>
              <option value="username">Orden: usuario</option>
            </select>

            <button
              onClick={() => setOnlyFollowers((v) => !v)}
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
              onClick={() => setShowPosts((s) => !s)}
              className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-sm hover:bg-[var(--color-panel)]"
            >
              {showPosts ? 'Ocultar posts' : 'Ver posts'}
            </button>
          </div>

          {showPosts && <PostsDrawer event={event} onError={setError} />}

          <main className="flex-1">
            {counts.isError ? (
              <p className="py-12 text-center text-sm text-[var(--color-red)]">
                No se pudo cargar. ¿Está corriendo el backend en :8000?
              </p>
            ) : view === 'board' ? (
              <Board
                event={event}
                search={search || undefined}
                order={order}
                follows={follows}
                counts={{ red: c.red, yellow: c.yellow, green: c.green }}
              />
            ) : (
              <UsersTable
                query={{
                  event,
                  status: status || undefined,
                  search: search || undefined,
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
