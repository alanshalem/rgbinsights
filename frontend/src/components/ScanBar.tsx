import { useState } from 'react';
import { useRunningJob, useScanPosts } from '../api/hooks';
import { ApiError, toApiError } from '../api/client';
import { JobBusyNote } from './ui/JobBusyNote';

function parseUrls(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function ScanBar({
  event,
  eventName,
  primary,
  onError,
}: {
  event?: number;
  eventName?: string;
  /** The main next step right now (no posts yet): filled + glowing. */
  primary: boolean;
  onError: (err: ApiError | null) => void;
}) {
  const [raw, setRaw] = useState('');
  const scan = useScanPosts();
  const igBusy = useRunningJob() !== undefined; // one Instagram job at a time
  const waiting = igBusy && !scan.isPending; // another job holds Instagram

  const handleScan = () => {
    const urls = parseUrls(raw);
    if (urls.length === 0 || scan.isPending || igBusy) return;
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

  const look = primary
    ? 'bg-green text-bg shadow-[0_0_24px_-6px_var(--color-green)] hover:opacity-90'
    : 'border border-green/60 text-green hover:bg-green/10';

  return (
    <div className="rounded-2xl border border-border bg-panel p-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleScan()}
          placeholder="Pegá el link de un post (instagram.com/p/…)"
          aria-label="Links de posts para escanear"
          className="flex-1 rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-muted"
        />
        <button
          type="button"
          onClick={handleScan}
          disabled={scan.isPending || igBusy || parseUrls(raw).length === 0}
          className={`rounded-lg px-4 py-2 text-sm font-semibold transition-opacity disabled:opacity-40 ${look}`}
        >
          {scan.isPending ? 'Escaneando…' : 'Escanear'}
        </button>
      </div>
      {waiting ? (
        <JobBusyNote />
      ) : event ? (
        <p className="mt-2 text-xs text-muted">
          Los posts se suman a <b className="text-ink">{eventName}</b>. Podés pegar varios links
          juntos.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted">
          Sin fiesta elegida: los posts quedan sin asignar. Elegí o creá una fiesta arriba para
          agruparlos.
        </p>
      )}
    </div>
  );
}
