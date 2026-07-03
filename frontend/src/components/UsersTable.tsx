import type { UserOut } from '../api/client';
import { summarize } from '../lib/user';
import { Avatar } from './Avatar';
import { TrafficChip } from './TrafficChip';

export function UsersTable({ users }: { users: UserOut[] }) {
  if (users.length === 0) {
    return (
      <p className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] py-12 text-center text-sm text-[var(--color-muted)]">
        Sin usuarios. Escaneá un post para empezar.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)]">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-[var(--color-border)] text-xs text-[var(--color-muted)]">
          <tr>
            <th className="px-4 py-3 font-medium">Usuario</th>
            <th className="px-4 py-3 font-medium">Estado</th>
            <th className="px-4 py-3 font-medium">Engagement</th>
            <th className="px-4 py-3 font-medium">Comentario</th>
            <th className="px-4 py-3 font-medium">Acción</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => {
            const { commented, liked, commentPreview } = summarize(u);
            return (
              <tr key={u.pk} className="border-b border-[var(--color-border)]/50 last:border-0">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2.5">
                    <Avatar user={u} size={32} />
                    <div className="min-w-0">
                      <div className="truncate font-medium">@{u.username}</div>
                      <div className="truncate text-xs text-[var(--color-muted)]">
                        {u.full_name}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <TrafficChip light={u.traffic_light} />
                </td>
                <td className="px-4 py-3 text-[var(--color-muted)]">
                  {[commented && 'comentó', liked && 'likeó'].filter(Boolean).join(' · ') || '—'}
                </td>
                <td className="max-w-[240px] px-4 py-3 text-[var(--color-muted)]">
                  <span className="line-clamp-1">{commentPreview ?? '—'}</span>
                </td>
                <td className="px-4 py-3">
                  <a
                    href={u.action_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-[var(--color-ink)] hover:underline"
                  >
                    {u.thread_id !== null ? 'Abrir DM' : 'Ver perfil'}
                  </a>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
