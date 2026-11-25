import type { JobKind } from '../api/hooks';

/** What the user sees for each kind of work: the toast title, the Actualizar ▾
 * entry, the busy button and the Actividad row all read this one map, so the
 * wording can't drift between screens. */
export type KindMeta = {
  icon: string;
  /** The action's name, the same everywhere (menu, toast, Actividad, Ayuda). */
  title: string;
  /** Shown on a busy button while this job runs. */
  busy: string;
};

export const JOB_META: Record<JobKind, KindMeta> = {
  scan: { icon: '🔍', title: 'Escanear posts', busy: 'Escaneando posts…' },
  sync: { icon: '🔄', title: 'Sincronizar DMs', busy: 'Sincronizando DMs…' },
  refresh: { icon: '↻', title: 'Re-escanear la fiesta + DMs', busy: 'Re-escaneando la fiesta…' },
  rescan: { icon: '↻', title: 'Re-escanear solo los posts', busy: 'Re-escaneando los posts…' },
  enrich: { icon: '👥', title: 'Quién te sigue + seguidores', busy: 'Buscando quién te sigue…' },
};

/** Non-job kinds that also show up in toasts or in Actividad. */
const OTHER_META: Record<string, KindMeta> = {
  campaign: { icon: '✉', title: 'Campaña de DMs', busy: 'Enviando…' },
  export: { icon: '⬇', title: 'Exportar lista', busy: 'Exportando…' },
};

/** Meta for any kind string the backend or the UI uses; unknown → `fallback`. */
export function kindMeta(kind: string, fallback = 'Tarea'): KindMeta {
  if (Object.hasOwn(JOB_META, kind)) return JOB_META[kind as JobKind];
  return OTHER_META[kind] ?? { icon: '•', title: fallback, busy: 'Trabajando…' };
}
