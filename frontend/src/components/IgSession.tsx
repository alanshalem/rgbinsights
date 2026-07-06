import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
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
  connected: 'bg-green',
  disconnected: 'bg-red',
};
const LABEL: Record<string, string> = {
  connected: 'IG conectado',
  disconnected: 'IG desconectado',
};

export function IgSession() {
  const qc = useQueryClient();
  const status = useIgStatus();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false); // reauth / sessionid in flight
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [showPaste, setShowPaste] = useState(false);
  const [sessionid, setSessionid] = useState('');
  const s = status.data;

  if (!s) return null;
  if (s.demo) {
    return (
      <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted">
        demo · sin IG
      </span>
    );
  }

  const refresh = () => void qc.invalidateQueries({ queryKey: ['ig-status'] });

  // Reconnect: saved session -> sessionid -> user/pass (handled server-side).
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
      // A challenge means user/pass hit a checkpoint — nudge toward the sessionid.
      setError(toApiError(e).message);
      setShowPaste(true);
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
    setError(null);
    setSuccess(false);
    setShowPaste(false);
    setSessionid('');
    void status.refetch();
  };

  const connected = s.state === 'connected';

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={`Instagram · última conexión ${ago(s.last_ok_at)}`}
        className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11px] font-medium hover:bg-panel"
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

            {success && (
              <div className="rounded-xl border border-green/40 bg-green/10 p-3 text-green">
                <p className="font-semibold">✓ ¡Conectado!</p>
                <p className="text-xs opacity-90">
                  Ya podés escanear posts y enviar los DMs de tu campaña.
                </p>
              </div>
            )}

            {busy && (
              <p className="flex items-center gap-2 text-yellow">
                <span className="h-2 w-2 animate-pulse rounded-full bg-yellow" />
                Conectando con Instagram… esperá unos segundos.
              </p>
            )}

            {error && (
              <div className="rounded-lg border border-red/40 bg-red/10 p-2.5 text-xs text-red">
                {error}
              </div>
            )}

            {connected && !success ? (
              <>
                <p className="text-muted">
                  <b className="text-green">Todo listo.</b> La app está conectada a tu Instagram y
                  puede escanear y enviar DMs. Última conexión {ago(s.last_ok_at)}.
                </p>
                <div className="flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={reauth}
                    disabled={busy}
                    className="mr-auto text-xs text-muted underline hover:text-ink disabled:opacity-50"
                  >
                    Reconectar igual
                  </button>
                  <button
                    type="button"
                    onClick={close}
                    className="rounded-lg bg-green px-4 py-2 font-semibold text-bg"
                  >
                    Listo
                  </button>
                </div>
              </>
            ) : (
              !success && (
                <>
                  {!showPaste && (
                    <p className="text-muted">
                      {s.has_credentials
                        ? 'Instagram cerró la sesión. Reconectá en un paso:'
                        : 'Pegá el sessionid de tu navegador para conectar.'}
                    </p>
                  )}

                  {!showPaste && s.has_credentials && (
                    <button
                      type="button"
                      onClick={reauth}
                      disabled={busy}
                      className="rounded-xl bg-blue px-4 py-3 text-center font-semibold text-bg disabled:opacity-50"
                    >
                      {busy ? 'Conectando…' : '🔄  Reconectar con Instagram'}
                      <span className="mt-0.5 block text-xs font-normal opacity-80">
                        Usa la cuenta ya configurada · automático
                      </span>
                    </button>
                  )}

                  {!showPaste ? (
                    <button
                      type="button"
                      onClick={() => {
                        setShowPaste(true);
                        setError(null);
                      }}
                      className="text-xs text-muted underline hover:text-ink"
                    >
                      {s.has_credentials
                        ? '¿No anduvo o te pide un código? Pegá tu sesión →'
                        : 'Pegá tu sesión de Instagram →'}
                    </button>
                  ) : (
                    <div className="flex flex-col gap-2">
                      <p className="font-semibold">Pegá tu sesión de Instagram</p>
                      <ol className="flex list-decimal flex-col gap-1 pl-5 text-xs text-muted">
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
                        className="w-full resize-none rounded-lg border border-border bg-panel px-3 py-2 font-mono text-xs"
                      />
                    </div>
                  )}

                  <div className="flex justify-end gap-2">
                    {showPaste && (
                      <button
                        type="button"
                        onClick={() => setShowPaste(false)}
                        className="mr-auto rounded-lg border border-border px-4 py-2"
                      >
                        ← Volver
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={close}
                      className="rounded-lg border border-border px-4 py-2"
                    >
                      Cerrar
                    </button>
                    {showPaste && (
                      <button
                        type="button"
                        onClick={saveSessionid}
                        disabled={busy || !sessionid.trim()}
                        className="rounded-lg bg-blue px-4 py-2 font-semibold text-bg disabled:opacity-50"
                      >
                        {busy ? 'Guardando…' : 'Guardar y conectar'}
                      </button>
                    )}
                  </div>
                </>
              )
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
