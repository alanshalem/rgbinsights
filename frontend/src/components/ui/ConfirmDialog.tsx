import { useCallback, useRef, useState, type ReactNode } from 'react';
import { Modal } from './Modal';
import { ConfirmContext, type ConfirmOptions } from './confirmContext';

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

/** Renders the in-app confirm dialog; see confirmContext.ts for useConfirm(). */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);

  const confirm = useCallback(
    (opts: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        pendingRef.current?.resolve(false); // a newer question replaces an open one
        const next = { ...opts, resolve };
        pendingRef.current = next;
        setPending(next);
      }),
    []
  );

  const answer = useCallback((ok: boolean) => {
    pendingRef.current?.resolve(ok);
    pendingRef.current = null;
    setPending(null);
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <Modal onClose={() => answer(false)} label={pending.title} center>
          <div className="flex flex-col gap-3 text-sm">
            <h2 className="display text-lg font-black tracking-tight uppercase">{pending.title}</h2>
            <div className="text-muted">{pending.message}</div>
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => answer(false)}
                className="rounded-lg border border-border px-4 py-2 font-semibold hover:bg-panel-2"
              >
                {pending.cancelLabel ?? 'Cancelar'}
              </button>
              <button
                type="button"
                autoFocus
                onClick={() => answer(true)}
                className={`rounded-lg px-4 py-2 font-semibold text-bg transition hover:brightness-110 ${
                  pending.danger ? 'bg-red' : 'bg-blue'
                }`}
              >
                {pending.confirmLabel ?? 'Confirmar'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </ConfirmContext.Provider>
  );
}
