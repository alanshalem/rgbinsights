import { useState } from 'react';
import { ApiError, api, toApiError, type ExportFormat, type ExportQuery } from '../../api/client';
import { notify } from '../../lib/notices';

const LABEL: Record<ExportFormat, string> = { xlsx: '⬇ Excel', pdf: '⬇ PDF' };
const NAME: Record<ExportFormat, string> = { xlsx: 'Excel', pdf: 'PDF' };

function people(n: number): string {
  return `${n} persona${n === 1 ? '' : 's'}`;
}

/** "⬇ Excel / ⬇ PDF": downloads exactly what the screen shows (same fiesta,
 * filters, search and order — every row, not only the loaded page), and says
 * so on screen. `count` is the on-screen total the counts already give us.
 * Reads the local DB only: no Instagram request. */
export function ExportButtons({
  query,
  count,
  scope,
  filters,
  onError,
}: {
  query: ExportQuery;
  count: number;
  /** The fiesta's name, or "Todas las fiestas". */
  scope: string;
  /** The active filters in plain words (see lib/filters). */
  filters: string[];
  onError: (e: ApiError | null) => void;
}) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const empty = count === 0;

  async function run(format: ExportFormat) {
    if (busy || empty) return;
    setBusy(format);
    onError(null);
    try {
      await api.exportUsers(format, query);
      notify('export', `Listo: se descargó la lista en ${NAME[format]} (${people(count)}).`);
    } catch (e) {
      onError(toApiError(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 md:ml-auto">
      <span className="text-xs text-muted">
        {empty
          ? 'No hay nada para exportar'
          : `Baja lo que ves: ${[scope, people(count), ...filters].join(' · ')}`}
      </span>
      {(['xlsx', 'pdf'] as const).map((format) => (
        <button
          key={format}
          type="button"
          onClick={() => void run(format)}
          disabled={busy !== null || empty}
          aria-label={`Descargar en ${NAME[format]} la lista que estás viendo`}
          title={
            empty
              ? 'No hay nada para exportar'
              : 'Descargar la lista que estás viendo (con los filtros y el orden actuales)'
          }
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-panel disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === format ? 'Exportando…' : LABEL[format]}
        </button>
      ))}
    </div>
  );
}
