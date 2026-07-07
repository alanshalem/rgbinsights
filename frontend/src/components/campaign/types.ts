import type { SendParams } from '../../lib/campaign';

export type Params = SendParams;

/** How the red list is filtered/ordered by follow status. */
export type Audience = 'only' | 'first' | 'all';

export const DEFAULT_MSG =
  'Hola {nombre}, ¿cómo estás? Vi que te copó RGB 🔴🟢🔵 — se viene fecha nueva y te queríamos invitar. Cualquier cosa te paso la data 🙌';

export const PRESET_LABEL: Record<string, string> = {
  optimo: 'Óptimo (recomendado)',
  max: 'Máxima cautela',
  media: 'Media cautela',
  custom: 'Custom',
};

export const AUDIENCE: { key: Audience; label: string; hint: string }[] = [
  {
    key: 'only',
    label: 'Solo a los que me siguen (recomendado)',
    hint: 'Lo más seguro: casi nunca bloquean un DM a un seguidor. Llega a menos gente.',
  },
  {
    key: 'first',
    label: 'Seguidores primero',
    hint: 'Le manda a todos los rojos, pero arranca por los que te siguen. Más alcance, más riesgo de bloqueo.',
  },
  {
    key: 'all',
    label: 'Todos, sin orden',
    hint: 'Todos los rojos en el orden del board. Máximo alcance, más riesgo.',
  },
];

// Matches a URL with or without scheme: word(.word)+.tld optional /path.
// Requires a 2+ letter TLD so "etc." / "8pm" don't match.
const LINK_RE = /\b(?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/\S*)?/gi;

/** True if the text carries a link (bare domain or full URL). */
export function hasLink(text: string): boolean {
  return new RegExp(LINK_RE.source, 'i').test(text);
}

/** Drop any link from the text — for a link-free first-contact DM (lower ban risk). */
export function stripLinks(text: string): string {
  return text
    .replace(LINK_RE, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export function audienceToFlags(a: Audience): {
  only_followers: boolean;
  followers_first: boolean;
} {
  return {
    only_followers: a === 'only',
    followers_first: a === 'only' || a === 'first',
  };
}
