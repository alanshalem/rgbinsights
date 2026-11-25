import type { SendParams } from '../../lib/campaign';

export type Params = SendParams;

/** How the red list is filtered/ordered by follow status. */
export type Audience = 'only' | 'first' | 'all';

export const DEFAULT_MSG =
  'Hola {nombre}, ¿cómo estás? Vi que te copó RGB 🔴🟢🔵 — se viene fecha nueva y te queríamos invitar. Cualquier cosa te paso la data 🙌';

/** The preset the form starts on: the slowest fixed pace (backend PRESETS
 * "max": longest waits, lowest daily cap). The same one is called
 * "(recomendado)" here, in the risk note and in Ayuda. */
export const RECOMMENDED_PRESET = 'max';

export const PRESET_LABEL: Record<string, string> = {
  max: 'Máxima cautela (recomendado)',
  media: 'Media cautela',
  optimo: 'Automático (~2-3 días)',
  custom: 'A mano',
};

export const AUDIENCE: { key: Audience; label: string; short: string; hint: string }[] = [
  {
    key: 'only',
    label: 'Solo a los que me siguen (recomendado)',
    short: 'solo a los que te siguen',
    hint: 'Lo más seguro: casi nunca bloquean un DM a un seguidor. Llega a menos gente.',
  },
  {
    key: 'first',
    label: 'Seguidores primero',
    short: 'seguidores primero',
    hint: 'Le manda a todos los rojos, pero arranca por los que te siguen. Más alcance, más riesgo de bloqueo.',
  },
  {
    key: 'all',
    label: 'Todos, sin orden',
    short: 'todos los rojos',
    hint: 'Todos los rojos, en el orden de la lista. Máximo alcance, más riesgo.',
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
