import { useState } from 'react';
import { useScanPosts, useSyncDms } from '../api/hooks';
import { ApiError } from '../api/client';

function parseUrls(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function ScanBar({ onError }: { onError: (err: ApiError | null) => void }) {
  const [raw, setRaw] = useState('');
  const scan = useScanPosts();
  const sync = useSyncDms();

  const busy = scan.isPending || sync.isPending;

  const handleScan = () => {
    const urls = parseUrls(raw);
    if (urls.length === 0) return;
    onError(null);
    scan.mutate(urls, {
      onError: (e) => onError(e instanceof ApiError ? e : new ApiError(0, 'unknown', String(e))),
      onSuccess: () => setRaw(''),
    });
  };

  const handleSync = () => {
    onError(null);
    sync.mutate(undefined, {
      onError: (e) => onError(e instanceof ApiError ? e : new ApiError(0, 'unknown', String(e))),
    });
  };

  return (
    <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] p-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleScan()}
          placeholder="Pegá una o varias URLs de posts…"
          className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-muted)]"
        />
        <button
          onClick={handleScan}
          disabled={busy || parseUrls(raw).length === 0}
          className="rounded-lg bg-[var(--color-green)] px-4 py-2 text-sm font-semibold text-[var(--color-bg)] transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {scan.isPending ? 'Escaneando…' : 'Escanear'}
        </button>
        <button
          onClick={handleSync}
          disabled={busy}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-panel-2)] px-4 py-2 text-sm font-semibold transition-colors hover:bg-[var(--color-border)] disabled:opacity-40"
        >
          {sync.isPending ? 'Sincronizando…' : 'Sincronizar DMs'}
        </button>
      </div>
      {scan.isSuccess && (
        <p className="mt-2 text-xs text-[var(--color-muted)]">
          {scan.data.results.length} post(s) · {scan.data.total_users_found} usuarios ·{' '}
          {scan.data.total_new_users} nuevos.
        </p>
      )}
      {sync.isSuccess && (
        <p className="mt-2 text-xs text-[var(--color-muted)]">
          {sync.data.threads_synced} hilos de DM sincronizados.
        </p>
      )}
    </div>
  );
}
