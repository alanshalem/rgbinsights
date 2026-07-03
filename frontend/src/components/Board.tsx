import type { TrafficLight, UserOut } from '../api/client';
import { LIGHTS, LIGHT_HINT, LIGHT_LABEL } from '../lib/user';
import { UserCard } from './UserCard';

const ACCENT: Record<TrafficLight, string> = {
  red: 'var(--color-red)',
  yellow: 'var(--color-yellow)',
  green: 'var(--color-green)',
};

function Column({ light, users }: { light: TrafficLight; users: UserOut[] }) {
  return (
    <section className="flex min-w-0 flex-1 flex-col rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)]/40">
      <header
        className="rounded-t-2xl border-t-2 px-4 py-3"
        style={{ borderTopColor: ACCENT[light] }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: ACCENT[light] }} />
            <h2 className="font-semibold">{LIGHT_LABEL[light]}</h2>
          </div>
          <span className="text-sm text-[var(--color-muted)]">{users.length}</span>
        </div>
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">{LIGHT_HINT[light]}</p>
      </header>
      <div className="flex flex-col gap-2.5 overflow-y-auto p-3">
        {users.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--color-muted)]">—</p>
        ) : (
          users.map((u) => <UserCard key={u.pk} user={u} />)
        )}
      </div>
    </section>
  );
}

export function Board({ users }: { users: UserOut[] }) {
  const byLight: Record<TrafficLight, UserOut[]> = { red: [], yellow: [], green: [] };
  for (const u of users) byLight[u.traffic_light].push(u);

  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start">
      {LIGHTS.map((light) => (
        <Column key={light} light={light} users={byLight[light]} />
      ))}
    </div>
  );
}
