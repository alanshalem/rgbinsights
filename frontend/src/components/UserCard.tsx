import type { UserOut } from '../api/client';
import { followLabel, formatCount, summarize } from '../lib/user';
import { Avatar } from './Avatar';
import { PostLink } from './PostLink';

const CHIP_CLS = 'rounded-full border border-border bg-panel-2 px-2 py-0.5 text-[11px] text-muted';

function Chip({ children, url, title }: { children: string; url?: string | null; title?: string }) {
  if (url) {
    return (
      <PostLink
        url={url}
        title={title}
        className={`${CHIP_CLS} hover:border-muted/60 hover:text-ink`}
      >
        {children}
      </PostLink>
    );
  }
  return <span className={CHIP_CLS}>{children}</span>;
}

const FOLLOW_STYLE = {
  mutual: 'border-green/50 bg-green/10 text-green',
  follows: 'border-blue/50 bg-blue/10 text-blue',
  no: 'border-border text-muted',
};

export function UserCard({ user }: { user: UserOut }) {
  const { commented, liked, commentPreview, commentUrl, likeUrl } = summarize(user);
  const hasThread = user.thread_id !== null;
  const regular = user.engagement_count >= 2;
  const follow = followLabel(user);
  const followers = formatCount(user.follower_count);
  const eventPct =
    user.event_posts_total > 1 ? `${user.event_engaged}/${user.event_posts_total} posts` : null;

  return (
    <div className="rounded-xl border border-border bg-panel p-3 transition-[transform,border-color,box-shadow] duration-150 hover:-translate-y-0.5 hover:border-muted/40 hover:shadow-lg hover:shadow-black/20">
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
                className="ml-auto shrink-0 rounded-full bg-red/15 px-1.5 py-0.5 text-[10px] font-semibold text-red"
              >
                🔥 {user.engagement_count}
              </span>
            )}
          </div>
          {user.full_name && <div className="truncate text-xs text-muted">{user.full_name}</div>}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {follow && (
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${FOLLOW_STYLE[follow.kind]}`}
              >
                {follow.text}
              </span>
            )}
            {followers && <Chip>{`🌟 ${followers}`}</Chip>}
            {commented && (
              <Chip url={commentUrl} title="Abrir el comentario en Instagram">
                comentó
              </Chip>
            )}
            {liked && (
              <Chip url={likeUrl} title="Abrir el post que likeó">
                likeó
              </Chip>
            )}
            {eventPct && <Chip>{eventPct}</Chip>}
          </div>
          {commentPreview && (
            <PostLink
              url={commentUrl}
              title="Abrir el comentario en Instagram"
              className="mt-2 line-clamp-2 block text-sm text-ink/80 italic hover:text-ink"
            >
              “{commentPreview}”
            </PostLink>
          )}
        </div>
      </div>
      <a
        href={user.action_url}
        target="_blank"
        rel="noreferrer"
        className="mt-3 block rounded-lg bg-panel-2 py-1.5 text-center text-sm font-medium text-ink transition-colors hover:bg-border"
      >
        {hasThread ? 'Abrir DM' : 'Ver perfil'}
      </a>
    </div>
  );
}
