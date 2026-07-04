import type { TrafficLight, UserOut } from '../api/client';

export type EngagementSummary = {
  commented: boolean;
  liked: boolean;
  commentPreview: string | null;
};

export function summarize(user: UserOut): EngagementSummary {
  let commented = false;
  let liked = false;
  let commentPreview: string | null = null;
  for (const e of user.engagements) {
    if (e.type === 'comment') {
      commented = true;
      if (!commentPreview && e.comment_text) commentPreview = e.comment_text;
    }
    if (e.type === 'like') liked = true;
  }
  return { commented, liked, commentPreview };
}

export function initials(user: UserOut): string {
  const base = user.full_name.trim() || user.username;
  const parts = base.split(/\s+/).slice(0, 2);
  return parts.map((p) => p.charAt(0).toUpperCase()).join('') || '?';
}

export const LIGHTS: readonly TrafficLight[] = ['red', 'yellow', 'green'] as const;

export const LIGHT_LABEL: Record<TrafficLight, string> = {
  red: 'Rojo',
  yellow: 'Amarillo',
  green: 'Verde',
};

export const LIGHT_HINT: Record<TrafficLight, string> = {
  red: 'Sin interacción por DM',
  yellow: 'Le escribimos, no contestó',
  green: 'Conversación real por DM',
};

/** null = relación no sincronizada todavía. */
export function followLabel(
  user: UserOut
): { text: string; kind: 'mutual' | 'follows' | 'no' } | null {
  if (user.follows_us == null) return null;
  if (user.follows_us && user.we_follow) return { text: 'mutuo', kind: 'mutual' };
  if (user.follows_us) return { text: 'te sigue', kind: 'follows' };
  return { text: 'no te sigue', kind: 'no' };
}

export function formatCount(n: number | null | undefined): string | null {
  if (n == null) return null;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}
