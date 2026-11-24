import { useState } from 'react';
import { ApiError, api, toApiError, type ExportFormat, type ExportQuery } from '../../api/client';

const LABEL: Record<ExportFormat, string> = { xlsx: 'Exportar Excel', pdf: 'Exportar PDF' };

/** "Exportar Excel / PDF": downloads exactly what the screen shows (same fiesta,
 * filters, search and order — every row, not only the loaded page). Reads the
 * local DB only: no Instagram request. */
export function ExportButtons({
  query,
  onError,
}: {
  query: ExportQuery;
  onError: (e: ApiError | null) => void;
}) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);

  async function run(format: ExportFormat) {
    if (busy) return;
    setBusy(format);
    onError(null);
    try {
      await api.exportUsers(format, query);
    } catch (e) {
      onError(toApiError(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex items-center gap-2 md:ml-auto">
      {(['xlsx', 'pdf'] as const).map((format) => (
        <button
          key={format}
          type="button"
          onClick={() => void run(format)}
          disabled={busy !== null}
          title="Descargar la lista que estás viendo (con los filtros y el orden actuales)"
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-panel disabled:cursor-wait disabled:opacity-60"
        >
          {busy === format ? 'Exportando…' : LABEL[format]}
        </button>
      ))}
    </div>
  );
}
