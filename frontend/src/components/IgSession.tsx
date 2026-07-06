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
  const [flow, setFlow] = useState<Flow>('idle'); // playwright browser-login flow
  const [busy, setBusy] = useState(false); // instagrapi reauth / sessionid in flight
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [showPaste, setShowPaste] = useState(false);
  const [sessionid, setSessionid] = useState('');
  const s = status.data;

  // Playwright only: while waiting, poll — the backend closes the login window
  // and confirms once the user is logged in.
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

  const refresh = () => void qc.invalidateQueries({ queryKey: ['ig-status'] });

  const startBrowserLogin = async () => {
    setError(null);
    try {
      await api.igLogin();
      setFlow('waiting');
    } catch (e) {
      setError(toApiError(e).message);
    }
  };

  const reauth = async () => {
    setError(null);
    setSuccess(false);
    setBusy(true);
    try {
      const r = await api.igReauth();
      refresh();
      if (r.state === 'connected') setSuccess(true);
      else setError('No se pudo conectar con la cuenta guardada. Probá pegar tu sesión (abajo).');
    } catch (e) {
      setError(`${toApiError(e).message}`);
      setShowPaste(true); // challenge / bad creds → guide them to the sessionid
    } finally {
      setBusy(false);
    }
  };

  const saveSessionid = async () => {
    const value = sessionid.trim();
    if (!value) return;
    setError(null);
    setSuccess(false);
    setBusy(true);
    try {
      const r = await api.igSetSessionid(value);
      refresh();
      setSessionid('');
      if (r.state === 'connected') {
        setSuccess(true);
        setShowPaste(false);
      } else {
        setError('Ese código no funcionó. Copiá uno recién sacado del navegador (paso 5).');
      }
    } catch (e) {
      setError(toApiError(e).message);
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    setOpen(false);
    setFlow('idle');
    setError(null);
    setSuccess(false);
    setShowPaste(false);
    setSessionid('');
    void status.refetch();
  };

  const isPlaywright = s.source === 'playwright';
  const connected = s.state === 'connected';

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
          <div className="flex w-[22rem] max-w-full flex-col gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${DOT[s.state] ?? DOT.disconnected}`} />
              <h2 className="display text-lg font-black tracking-tight uppercase">
                Conexión con Instagram
              </h2>
            </div>

            {/* Success banner — shown after a successful reconnect. */}
            {success && (
              <div className="rounded-xl border border-[var(--color-green)]/40 bg-[var(--color-green)]/10 p-3 text-[var(--color-green)]">
                <p className="font-semibold">✓ ¡Conectado!</p>
                <p className="text-xs opacity-90">
                  Ya podés escanear posts y enviar los DMs de tu campaña.
                </p>
              </div>
            )}

            {/* Busy banner — the reconnect is a few-second network login. */}
            {busy && (
              <p className="flex items-center gap-2 text-[var(--color-yellow)]">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--color-yellow)]" />
                Conectando con Instagram… esperá unos segundos.
              </p>
            )}

            {error && (
              <div className="rounded-lg border border-[var(--color-red)]/40 bg-[var(--color-red)]/10 p-2.5 text-xs text-[var(--color-red)]">
                {error}
              </div>
            )}

            {/* ---------------- CONNECTED ---------------- */}
            {connected && !success && (
              <>
                <p className="text-[var(--color-muted)]">
                  <b className="text-[var(--color-green)]">Todo listo.</b> La app está conectada a tu
                  Instagram y puede escanear y enviar DMs. Última conexión {ago(s.last_ok_at)}.
                </p>
                <div className="flex items-center justify-end gap-3">
                  {!isPlaywright && (
                    <button
                      onClick={reauth}
                      disabled={busy}
                      className="mr-auto text-xs text-[var(--color-muted)] underline hover:text-[var(--color-ink)] disabled:opacity-50"
                    >
                      Reconectar igual
                    </button>
                  )}
                  <button
                    onClick={close}
                    className="rounded-lg bg-[var(--color-green)] px-4 py-2 font-semibold text-[var(--color-bg)]"
                  >
                    Listo
                  </button>
                </div>
              </>
            )}

            {/* ---------------- DISCONNECTED ---------------- */}
            {!connected && (
              <>
                {!showPaste && (
                  <p className="text-[var(--color-muted)]">
                    Instagram cerró la sesión. Sin conexión <b>no se pueden enviar DMs</b>. Reconectá
                    en un paso:
                  </p>
                )}

                {isPlaywright ? (
                  // -------- Legacy playwright: headed browser --------
                  flow === 'waiting' ? (
                    <p className="flex items-center gap-2 text-[var(--color-yellow)]">
                      <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--color-yellow)]" />
                      Se abrió Chrome — logueate ahí y esperá…
                    </p>
                  ) : (
                    <button
                      onClick={startBrowserLogin}
                      className="rounded-lg bg-[var(--color-blue)] px-4 py-2.5 font-semibold text-[var(--color-bg)]"
                    >
                      Abrir Instagram para loguearme
                    </button>
                  )
                ) : (
                  // -------- Instagrapi: 1-click + guided sessionid --------
                  <>
                    {!showPaste && s.has_credentials && (
                      <button
                        onClick={reauth}
                        disabled={busy}
                        className="rounded-xl bg-[var(--color-blue)] px-4 py-3 text-center font-semibold text-[var(--color-bg)] disabled:opacity-50"
                      >
                        {busy ? 'Conectando…' : '🔄  Reconectar con Instagram'}
                        <span className="mt-0.5 block text-xs font-normal opacity-80">
                          Usa la cuenta ya configurada · automático
                        </span>
                      </button>
                    )}

                    {!showPaste ? (
                      <button
                        onClick={() => {
                          setShowPaste(true);
                          setError(null);
                        }}
                        className="text-xs text-[var(--color-muted)] underline hover:text-[var(--color-ink)]"
                      >
                        {s.has_credentials
                          ? '¿No anduvo o te pide un código? Pegá tu sesión →'
                          : 'Pegá tu sesión de Instagram →'}
                      </button>
                    ) : (
                      <div className="flex flex-col gap-2">
                        <p className="font-semibold">Pegá tu sesión de Instagram</p>
                        <ol className="flex list-decimal flex-col gap-1 pl-5 text-xs text-[var(--color-muted)]">
                          <li>
                            Abrí <b>instagram.com</b> en tu navegador, logueado a la cuenta del crew.
                          </li>
                          <li>
                            Apretá <b>F12</b> (abre las herramientas del navegador).
                          </li>
                          <li>
                            Arriba, entrá a la pestaña <b>Application</b> (o “Aplicación”).
                          </li>
                          <li>
                            A la izquierda: <b>Cookies</b> → <b>https://www.instagram.com</b>.
                          </li>
                          <li>
                            Buscá la fila <b>sessionid</b>, copiá el texto de la columna <b>Value</b>.
                          </li>
                          <li>Pegalo acá abajo y dale Guardar:</li>
                        </ol>
                        <textarea
                          value={sessionid}
                          onChange={(e) => setSessionid(e.target.value)}
                          placeholder="Pegá acá el sessionid (empieza con 70564…%3A…)"
                          rows={3}
                          className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] px-3 py-2 font-mono text-xs"
                        />
                      </div>
                    )}
                  </>
                )}

                <div className="flex justify-end gap-2">
                  {showPaste && (
                    <button
                      onClick={() => setShowPaste(false)}
                      className="mr-auto rounded-lg border border-[var(--color-border)] px-4 py-2"
                    >
                      ← Volver
                    </button>
                  )}
                  <button
                    onClick={close}
                    className="rounded-lg border border-[var(--color-border)] px-4 py-2"
                  >
                    Cerrar
                  </button>
                  {showPaste && (
                    <button
                      onClick={saveSessionid}
                      disabled={busy || !sessionid.trim()}
                      className="rounded-lg bg-[var(--color-blue)] px-4 py-2 font-semibold text-[var(--color-bg)] disabled:opacity-50"
                    >
                      {busy ? 'Guardando…' : 'Guardar y conectar'}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
