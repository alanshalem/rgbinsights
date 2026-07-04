import { useState } from 'react';
import { toApiError } from '../api/client';
import { useResetAll } from '../api/hooks';
import { Modal } from './Modal';

const PHRASE = 'BORRAR TODO';

export function ResetModal({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, number> | null>(null);
  const reset = useResetAll();
  const armed = text.trim() === PHRASE;

  const run = () => {
    setError(null);
    reset.mutate(text.trim(), {
      onSuccess: (r) => setDone(r.deleted),
      onError: (e) => setError(toApiError(e).message),
    });
  };

  return (
    <Modal onClose={onClose} center>
      <div className="flex flex-col gap-3 text-sm">
        <h2 className="display text-lg font-black tracking-tight text-[var(--color-red)] uppercase">
          Borrar todo
        </h2>

        {done ? (
          <>
            <p className="text-[var(--color-green)]">✓ Listo. Se borró todo:</p>
            <ul className="mono flex flex-col gap-0.5 text-xs text-[var(--color-muted)]">
              {Object.entries(done).map(([table, n]) => (
                <li key={table}>
                  {table}: {n}
                </li>
              ))}
            </ul>
            <button
              onClick={onClose}
              className="mt-1 self-end rounded-lg bg-[var(--color-panel-2)] px-4 py-2 font-semibold"
            >
              Cerrar
            </button>
          </>
        ) : (
          <>
            <p className="text-[var(--color-muted)]">
              Borra <b>todo</b>: fiestas, posts, likes/comentarios, DMs, relaciones (te sigue),
              perfiles, campañas e historial. <b>No se puede deshacer</b> — solo se recupera
              volviendo a escanear.
            </p>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--color-muted)]">
                Escribí <b className="text-[var(--color-red)]">{PHRASE}</b> para confirmar
              </span>
              <input
                autoFocus
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && armed && run()}
                placeholder={PHRASE}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 outline-none focus:border-[var(--color-red)]"
              />
            </label>

            {error && <p className="text-xs text-[var(--color-red)]">{error}</p>}

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-lg border border-[var(--color-border)] px-4 py-2 font-semibold"
              >
                Cancelar
              </button>
              <button
                onClick={run}
                disabled={!armed || reset.isPending}
                className="rounded-lg bg-[var(--color-red)] px-4 py-2 font-semibold text-[var(--color-bg)] disabled:opacity-40"
              >
                {reset.isPending ? 'Borrando…' : 'Borrar todo'}
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
