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
    label: 'Solo a los que me siguen',
    hint: 'Lo más seguro: casi nunca bloquean un DM a un seguidor. Llega a menos gente.',
  },
  {
    key: 'first',
    label: 'Seguidores primero (recomendado)',
    hint: 'Le manda a todos los rojos, pero arranca por los que te siguen. Equilibra alcance y riesgo.',
  },
  {
    key: 'all',
    label: 'Todos, sin orden',
    hint: 'Todos los rojos en el orden del board. Máximo alcance, más riesgo.',
  },
];

export function audienceToFlags(a: Audience): {
  only_followers: boolean;
  followers_first: boolean;
} {
  return {
    only_followers: a === 'only',
    followers_first: a === 'only' || a === 'first',
  };
}
