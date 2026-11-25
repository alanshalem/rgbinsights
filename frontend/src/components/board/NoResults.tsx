import { describeFilters, hasFilters, type ActiveFilters } from '../../lib/filters';

/** The empty list: "nobody matches these filters" (with a way out), or "there
 * is nobody yet" (with the next step). Never blames the user for no data. */
export function NoResults({ filters, onClear }: { filters: ActiveFilters; onClear: () => void }) {
  const filtered = hasFilters(filters);
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-panel px-4 py-12 text-center text-sm text-muted">
      {filtered ? (
        <>
          <p>
            Nadie coincide con{' '}
            <span className="text-ink">{describeFilters(filters).join(' · ')}</span>.
          </p>
          <button
            type="button"
            onClick={onClear}
            className="rounded-lg border border-border px-3 py-1.5 text-ink hover:bg-panel-2"
          >
            Limpiar filtros
          </button>
        </>
      ) : (
        <p>
          Todavía no hay nadie acá. Pegá los links de los posts de la fiesta arriba y tocá{' '}
          <b className="text-ink">Escanear</b>.
        </p>
      )}
    </div>
  );
}
