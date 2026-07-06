/** Feedback line + the "1 DM de prueba" box + the launch button (right column). */
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
      {error && <p className="text-xs text-red">{error}</p>}
      {testedTo && <p className="text-xs text-green">✓ Mensaje de prueba enviado a @{testedTo}.</p>}

      {/* test send — one DM to check it lands before the batch */}
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-bg p-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted">
            Probá primero: mandá 1 DM (por defecto, al primero de la lista)
          </span>
          <input
            list="test-targets"
            value={testTarget}
            onChange={(e) => setTestTarget(e.target.value)}
            placeholder={redUsers[0] ? `@${redUsers[0].username}` : '@usuario'}
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
          disabled={testBusy || count === 0}
          className="w-full rounded-lg border border-border px-4 py-2 font-semibold hover:bg-panel disabled:opacity-40"
        >
          {testBusy ? 'Enviando…' : 'Enviar 1 de prueba'}
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
