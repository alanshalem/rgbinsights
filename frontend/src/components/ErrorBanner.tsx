import type { ApiError } from '../api/client';

/** The dismissable-looking error strip under the toolbar. A challenge/expired
 * session gets the amber "reconnect" copy; everything else is a red error. */
export function ErrorBanner({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className={`rounded-xl border px-4 py-3 text-sm ${
        error.isChallenge
          ? 'border-[var(--color-yellow)]/50 bg-[var(--color-yellow)]/10 text-[var(--color-yellow)]'
          : 'border-[var(--color-red)]/50 bg-[var(--color-red)]/10 text-[var(--color-red)]'
      }`}
    >
      {error.isChallenge ? (
        <>
          <strong>Instagram pide verificación.</strong> La sesión se venció: reconectá desde el chip{' '}
          <b>IG</b> arriba a la derecha y reintentá. {error.message}
        </>
      ) : (
        <>Error: {error.message}</>
      )}
    </div>
  );
}
