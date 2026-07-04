import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, toApiError } from '../api/client';
import { useIgStatus } from '../api/hooks';
import { Modal } from './Modal';

function ago(iso: string | null | undefined): string {
  if (!iso) return 'nunca';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'recién';
  if (mins < 60) return `hace ${mins}min`;
  const h = Math.floor(mins / 60);
  return h < 24 ? `hace ${h}h` : `hace ${Math.floor(h / 24)}d`;
}

const DOT: Record<string, string> = {
  connected: 'bg-[var(--color-green)]',
  disconnected: 'bg-[var(--color-red)]',
  logging_in: 'bg-[var(--color-yellow)]',
};
const LABEL: Record<string, string> = {
  connected: 'IG conectado',
  disconnected: 'IG desconectado',
  logging_in: 'IG conectando…',
};

type Flow = 'idle' | 'waiting' | 'done';

export function IgSession() {
  const qc = useQueryClient();
  const status = useIgStatus();
  const [open, setOpen] = useState(false);
  const [flow, setFlow] = useState<Flow>('idle');
  const [error, setError] = useState<string | null>(null);
  const s = status.data;

  // While waiting, poll the backend: it closes the login window and confirms
  // once the user is logged in.
  useQuery({
    queryKey: ['ig-login-finish'],
    queryFn: async () => {
      const r = await api.igLoginFinish();
      if (r.logged_in) {
        setFlow('done');
        void qc.invalidateQueries({ queryKey: ['ig-status'] });
      }
      return r;
    },
    enabled: flow === 'waiting',
    refetchInterval: 2500,
  });

  if (!s) return null;
  if (s.demo) {
    return (
      <span className="rounded-full border border-[var(--color-border)] px-2 py-0.5 text-[11px] text-[var(--color-muted)]">
        demo · sin IG
      </span>
    );
  }

  const startLogin = async () => {
    setError(null);
    try {
      await api.igLogin();
      setFlow('waiting');
    } catch (e) {
      setError(toApiError(e).message);
    }
  };

  const close = () => {
    setOpen(false);
    setFlow('idle');
    setError(null);
    void status.refetch();
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={`Instagram · última conexión ${ago(s.last_ok_at)}`}
        className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-medium hover:bg-[var(--color-panel)]"
      >
        <span className={`h-2 w-2 rounded-full ${DOT[s.state] ?? DOT.disconnected}`} />
        <span className="hidden sm:inline">{LABEL[s.state] ?? 'IG'}</span>
      </button>

      {open && (
        <Modal onClose={close} center>
          <div className="flex flex-col gap-3 text-sm">
            <h2 className="display text-lg font-black tracking-tight uppercase">
              Conexión con Instagram
            </h2>

            {flow === 'done' ? (
              <>
                <p className="text-[var(--color-green)]">✓ Conectado. Ya podés usar la app.</p>
                <button
                  onClick={close}
                  className="self-end rounded-lg bg-[var(--color-green)] px-4 py-2 font-semibold text-[var(--color-bg)]"
                >
                  Listo
                </button>
              </>
            ) : flow === 'waiting' ? (
              <>
                <p className="text-[var(--color-muted)]">
                  Se abrió una <b>ventana de Chrome</b>. Logueate ahí con la cuenta del crew. Cuando
                  entres al feed (sin captcha), esto se conecta solo.
                </p>
                <p className="flex items-center gap-2 text-[var(--color-yellow)]">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--color-yellow)]" />
                  Esperando el login…
                </p>
                <button
                  onClick={close}
                  className="self-end rounded-lg border border-[var(--color-border)] px-4 py-2"
                >
                  Cancelar
                </button>
              </>
            ) : (
              <>
                <p className="text-[var(--color-muted)]">
                  Estado:{' '}
                  <b className={s.state === 'connected' ? 'text-[var(--color-green)]' : ''}>
                    {LABEL[s.state] ?? s.state}
                  </b>{' '}
                  · última conexión {ago(s.last_ok_at)}.
                </p>
                {s.state !== 'connected' && (
                  <p className="text-[var(--color-muted)]">
                    Si Instagram pide verificación o se venció la sesión, reconectá: se abre una
                    ventana para loguearte, sin usar la terminal.
                  </p>
                )}
                {error && <p className="text-xs text-[var(--color-red)]">{error}</p>}
                <div className="flex justify-end gap-2">
                  <button
                    onClick={close}
                    className="rounded-lg border border-[var(--color-border)] px-4 py-2"
                  >
                    Cerrar
                  </button>
                  <button
                    onClick={startLogin}
                    className="rounded-lg bg-[var(--color-blue)] px-4 py-2 font-semibold text-[var(--color-bg)]"
                  >
                    {s.state === 'connected' ? 'Reconectar igual' : 'Reconectar Instagram'}
                  </button>
                </div>
              </>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
