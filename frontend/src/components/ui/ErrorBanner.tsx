import type { ApiError } from '../../api/client';

/** The error strip under the toolbar, closable with ✕. No/expired session and
 * a challenge get the amber "what to do" copy; everything else is a red error. */
export function ErrorBanner({ error, onClose }: { error: ApiError | null; onClose: () => void }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${
        error.isChallenge
          ? 'border-yellow/50 bg-yellow/10 text-yellow'
          : 'border-red/50 bg-red/10 text-red'
      }`}
    >
      <p className="min-w-0 flex-1">
        {error.code === 'login_required' ? (
          <>
            <strong>Falta conectar Instagram.</strong> Tocá el chip <b>IG</b> arriba a la derecha →{' '}
            <b>Pegá tu sesión</b>, y después probá de nuevo. {error.message}
          </>
        ) : error.isChallenge ? (
          <>
            <strong>Instagram pide verificación.</strong> Confirmá que sos vos desde el celu, tocá
            el chip <b>IG</b> arriba a la derecha → <b>Volver a conectar</b> y probá de nuevo.{' '}
            {error.message}
          </>
        ) : (
          error.message
        )}
      </p>
      <button
        type="button"
        onClick={onClose}
        aria-label="Cerrar el aviso de error"
        title="Cerrar"
        className="-my-1 -mr-2 shrink-0 rounded px-2 py-1 hover:bg-black/20"
      >
        ✕
      </button>
    </div>
  );
}
