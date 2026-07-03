import { useState } from 'react';
import type { UserOut } from '../api/client';
import { initials } from '../lib/user';

export function Avatar({ user, size = 40 }: { user: UserOut; size?: number }) {
  const [broken, setBroken] = useState(false);
  const showImg = user.profile_pic_url && !broken;

  return (
    <div
      className="flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-[var(--color-panel-2)] text-sm font-semibold text-[var(--color-muted)]"
      style={{ width: size, height: size }}
    >
      {showImg ? (
        <img
          src={user.profile_pic_url ?? ''}
          alt={user.username}
          className="h-full w-full object-cover"
          onError={() => setBroken(true)}
        />
      ) : (
        initials(user)
      )}
    </div>
  );
}
