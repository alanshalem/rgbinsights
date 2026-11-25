import type { TrafficLight } from '../api/client';
import { LIGHT_LABEL } from './user';

/** The filters the user can set on top of the fiesta (search box, "Solo
 * seguidores", the table's color picker). */
export type ActiveFilters = {
  search?: string;
  onlyFollowers: boolean;
  status?: TrafficLight;
};

export function hasFilters(f: ActiveFilters): boolean {
  return Boolean(f.search) || f.onlyFollowers || f.status !== undefined;
}

/** The filters in plain words, e.g. ['“juan”', 'solo seguidores', 'solo Rojo'],
 * so the empty state and the export caption describe them the same way. */
export function describeFilters(f: ActiveFilters): string[] {
  const parts: string[] = [];
  if (f.search) parts.push(`“${f.search}”`);
  if (f.onlyFollowers) parts.push('solo seguidores');
  if (f.status) parts.push(`solo ${LIGHT_LABEL[f.status]}`);
  return parts;
}
