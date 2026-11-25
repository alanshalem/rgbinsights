import { useState } from 'react';
import { useRunningJob, useScanPosts } from '../api/hooks';
import { ApiError, toApiError } from '../api/client';

function parseUrls(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function ScanBar({
  event,
  eventName,
  onError,
}: {
  event?: number;
  eventName?: string;
  onError: (err: ApiError | null) => void;
}) {
  const [raw, setRaw] = useState('');
  const scan = useScanPosts();
  const igBusy = useRunningJob() !== undefined; // one Instagram job at a time

  const handleScan = () => {
    const urls = parseUrls(raw);
    if (urls.length === 0) return;
    onError(null);
    scan.mutate(
      { urls, eventId: event },
      {
        onError: (e) => onError(toApiError(e)),
        // Clear the URLs only on a known success (null = outcome unknown).
        onSuccess: (done) => {
          if (done) setRaw('');
        },
      }
    );
  };

  return (
    <div className="rounded-2xl border border-border bg-panel p-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleScan()}
          placeholder={
            event ? `Pegá URLs de posts para "${eventName}"…` : 'Pegá una o varias URLs de posts…'
          }
          className="flex-1 rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-muted"
        />
        <button
          type="button"
          onClick={handleScan}
          disabled={scan.isPending || igBusy || parseUrls(raw).length === 0}
          title={igBusy && !scan.isPending ? 'Esperá a que termine la tarea en curso' : undefined}
          className="rounded-lg bg-green px-4 py-2 text-sm font-semibold text-bg shadow-[0_0_24px_-6px_var(--color-green)] transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {scan.isPending ? 'Escaneando…' : 'Escanear'}
        </button>
      </div>
      {!event && (
        <p className="mt-2 text-xs text-muted">
          Sin fiesta seleccionada: los posts quedan sin asignar. Elegí o creá una fiesta arriba para
          agruparlos.
        </p>
      )}
    </div>
  );
}
