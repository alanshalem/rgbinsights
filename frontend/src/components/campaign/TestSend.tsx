/** Feedback line + the "1 DM real de prueba" box + the launch button (right column).
 *
 * The test is a real DM to a real person. The backend does not mark it locally:
 * that person stays 🔴 until the next "Sincronizar DMs", so a campaign launched
 * before that also includes them (the copy says so). */
export function TestSend({
  error,
  testedTo,
  redUsers,
  testTarget,
  setTestTarget,
  onTest,
  testBusy,
  onLaunch,
  launchBusy,
  count,
}: {
  error: string | null;
  testedTo: string | null;
  redUsers: { username: string; follows_us?: boolean | null }[];
  testTarget: string;
  setTestTarget: (s: string) => void;
  onTest: () => void;
  testBusy: boolean;
  onLaunch: () => void;
  launchBusy: boolean;
  count: number;
}) {
  return (
    <>
      {error &&
        (/action-block|frenó el env/i.test(error) ? (
          <div
            role="alert"
            className="rounded-lg border border-yellow/50 bg-yellow/10 p-3 text-xs text-yellow"
          >
            <p className="font-semibold">⚠ Instagram bloqueó el envío de DMs</p>
            <p className="mt-1 opacity-90">{error}</p>
          </div>
        ) : (
          <div
            role="alert"
            className="rounded-lg border border-red/40 bg-red/10 p-2.5 text-xs text-red"
          >
            {error}
          </div>
        ))}
      {testedTo && (
        <div role="status" className="text-xs">
          <p className="text-green">✓ DM de prueba enviado a @{testedTo}.</p>
          <p className="mt-1 text-muted">
            Sigue en 🔴 hasta que hagas <b>Actualizar ▾ → Sincronizar DMs</b>. Si lanzás la campaña
            antes, también le llega el mensaje de la campaña.
          </p>
        </div>
      )}

      {/* test send — one DM to check it lands before the batch */}
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-bg p-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-semibold text-yellow">
            ⚠ Es un DM real: le llega a esa persona. Elegí a alguien de confianza que te siga.
          </span>
          <span className="text-muted">
            Escribí su @. Tiene que estar entre los rojos de esta campaña.
          </span>
          <input
            list="test-targets"
            value={testTarget}
            onChange={(e) => setTestTarget(e.target.value)}
            placeholder="@usuario"
            className="w-full rounded-lg border border-border bg-panel px-3 py-2 outline-none"
          />
          <datalist id="test-targets">
            {redUsers.slice(0, 500).map((u) => (
              <option key={u.username} value={u.username}>
                {u.follows_us ? 'te sigue' : ''}
              </option>
            ))}
          </datalist>
        </label>
        <button
          type="button"
          onClick={onTest}
          disabled={testBusy || count === 0 || !testTarget.replace(/^@/, '').trim()}
          title={testTarget.trim() ? undefined : 'Escribí a quién le llega el DM de prueba'}
          className="w-full rounded-lg border border-border px-4 py-2 font-semibold hover:bg-panel disabled:opacity-40"
        >
          {testBusy ? 'Enviando…' : 'Enviar 1 DM real de prueba'}
        </button>
      </div>

      <button
        type="button"
        onClick={onLaunch}
        disabled={launchBusy || count === 0}
        className="w-full rounded-xl bg-red px-4 py-3 font-semibold text-bg shadow-[0_0_28px_-8px_var(--color-red)] transition hover:brightness-110 disabled:opacity-40"
      >
        {launchBusy ? 'Lanzando…' : `Lanzar campaña · ${count} DMs`}
      </button>
    </>
  );
}
