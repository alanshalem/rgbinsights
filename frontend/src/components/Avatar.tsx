import { useState } from 'react';
import { BASE, type UserOut } from '../api/client';
import { initials } from '../lib/user';

export function Avatar({ user, size = 40 }: { user: UserOut; size?: number }) {
  const [broken, setBroken] = useState(false);
  // Only try the image when IG gave us a pic URL at all; the backend proxy
  // caches it so it survives the CDN link expiring. On any failure → initials.
  const showImg = user.profile_pic_url && !broken;

  return (
    <div
      className="flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-[var(--color-panel-2)] text-sm font-semibold text-[var(--color-muted)]"
      style={{ width: size, height: size }}
    >
      {showImg ? (
        <img
          src={`${BASE}/avatar/${user.pk}`}
          alt={user.username}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => setBroken(true)}
        />
      ) : (
        initials(user)
      )}
    </div>
  );
}
