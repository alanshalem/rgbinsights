import type { UserOut } from '../api/client';
import { followLabel, formatCount, summarize } from '../lib/user';
import { Avatar } from './Avatar';

function Chip({ children }: { children: string }) {
  return (
    <span className="rounded-full border border-[var(--color-border)] bg-[var(--color-panel-2)] px-2 py-0.5 text-[11px] text-[var(--color-muted)]">
      {children}
    </span>
  );
}

const FOLLOW_STYLE = {
  mutual: 'border-[var(--color-green)]/50 bg-[var(--color-green)]/10 text-[var(--color-green)]',
  follows: 'border-[var(--color-blue)]/50 bg-[var(--color-blue)]/10 text-[var(--color-blue)]',
  no: 'border-[var(--color-border)] text-[var(--color-muted)]',
};

export function UserCard({ user }: { user: UserOut }) {
  const { commented, liked, commentPreview } = summarize(user);
  const hasThread = user.thread_id !== null;
  const regular = user.engagement_count >= 2;
  const follow = followLabel(user);
  const followers = formatCount(user.follower_count);
  const eventPct =
    user.event_posts_total > 1 ? `${user.event_engaged}/${user.event_posts_total} posts` : null;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-3 transition-colors hover:border-[var(--color-muted)]/40">
      <div className="flex items-start gap-3">
        <Avatar user={user} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <a
              href={`https://instagram.com/${user.username}/`}
              target="_blank"
              rel="noreferrer"
              className="truncate font-semibold hover:underline"
            >
              @{user.username}
            </a>
            {user.is_verified && <span title="verificado">✔️</span>}
            {user.is_private && <span title="cuenta privada">🔒</span>}
            {regular && (
              <span
                title={`enganchó ${user.engagement_count} posts en total`}
                className="ml-auto shrink-0 rounded-full bg-[var(--color-red)]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-red)]"
              >
                🔥 {user.engagement_count}
              </span>
            )}
          </div>
          {user.full_name && (
            <div className="truncate text-xs text-[var(--color-muted)]">{user.full_name}</div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {follow && (
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${FOLLOW_STYLE[follow.kind]}`}
              >
                {follow.text}
              </span>
            )}
            {followers && <Chip>{`🌟 ${followers}`}</Chip>}
            {commented && <Chip>comentó</Chip>}
            {liked && <Chip>likeó</Chip>}
            {eventPct && <Chip>{eventPct}</Chip>}
          </div>
          {commentPreview && (
            <p className="mt-2 line-clamp-2 text-sm text-[var(--color-ink)]/80 italic">
              “{commentPreview}”
            </p>
          )}
        </div>
      </div>
      <a
        href={user.action_url}
        target="_blank"
        rel="noreferrer"
        className="mt-3 block rounded-lg bg-[var(--color-panel-2)] py-1.5 text-center text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[var(--color-border)]"
      >
        {hasThread ? 'Abrir DM' : 'Ver perfil'}
      </a>
    </div>
  );
}
