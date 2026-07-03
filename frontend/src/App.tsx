import { useMemo, useState } from 'react';
import { ApiError, type TrafficLight, type UsersQuery } from './api/client';
import { usePosts, useUsers } from './api/hooks';
import { Board } from './components/Board';
import { ScanBar } from './components/ScanBar';
import { UsersTable } from './components/UsersTable';
import { TrafficDot } from './components/TrafficChip';
import { LIGHTS, LIGHT_LABEL } from './lib/user';

type View = 'board' | 'table';

export default function App() {
  const [view, setView] = useState<View>('board');
  const [status, setStatus] = useState<TrafficLight | ''>('');
  const [post, setPost] = useState('');
  const [search, setSearch] = useState('');
  const [order, setOrder] = useState<'username' | 'status'>('status');
  const [error, setError] = useState<ApiError | null>(null);

  const query: UsersQuery = useMemo(
    () => ({
      ...(status ? { status } : {}),
      ...(post ? { post } : {}),
      ...(search ? { search } : {}),
      order,
    }),
    [status, post, search, order]
  );

  const users = useUsers(query);
  const posts = usePosts();

  const counts = useMemo(() => {
    const c: Record<TrafficLight, number> = { red: 0, yellow: 0, green: 0 };
    for (const u of users.data ?? []) c[u.traffic_light]++;
    return c;
  }, [users.data]);

  return (
    <div className="mx-auto flex min-h-full max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="rgb-gradient">RGB</span> · Semáforo
          </h1>
          <p className="text-sm text-[var(--color-muted)]">
            Seguimiento de outreach por DM · @rgb.collective___
          </p>
        </div>
        <div className="flex gap-3 text-sm">
          {LIGHTS.map((l) => (
            <div key={l} className="flex items-center gap-1.5">
              <TrafficDot light={l} />
              <span className="font-semibold">{counts[l]}</span>
              <span className="text-[var(--color-muted)]">{LIGHT_LABEL[l]}</span>
            </div>
          ))}
        </div>
      </header>

      <ScanBar onError={setError} />

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
              <strong>Instagram pide verificación.</strong> Resolvé el challenge / 2FA y volvé a
              intentar. {error.message}
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
              className={`px-3 py-1.5 text-sm font-medium capitalize ${
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
          placeholder="Buscar @username…"
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-muted)]"
        />

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

        <select
          value={post}
          onChange={(e) => setPost(e.target.value)}
          className="max-w-[220px] rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm outline-none"
        >
          <option value="">Todos los posts</option>
          {(posts.data ?? []).map((p) => (
            <option key={p.media_pk} value={p.media_pk}>
              {p.shortcode} — {p.caption.slice(0, 24) || 'sin caption'}
            </option>
          ))}
        </select>

        <select
          value={order}
          onChange={(e) => setOrder(e.target.value as 'username' | 'status')}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-1.5 text-sm outline-none"
        >
          <option value="status">Orden: estado</option>
          <option value="username">Orden: usuario</option>
        </select>
      </div>

      <main className="flex-1">
        {users.isPending ? (
          <p className="py-12 text-center text-sm text-[var(--color-muted)]">Cargando…</p>
        ) : users.isError ? (
          <p className="py-12 text-center text-sm text-[var(--color-red)]">
            No se pudo cargar. ¿Está corriendo el backend en :8000?
          </p>
        ) : view === 'board' ? (
          <Board users={users.data} />
        ) : (
          <UsersTable users={users.data} />
        )}
      </main>
    </div>
  );
}
