import { useState } from 'react';
import { useCreateEvent } from '../api/hooks';
import { ApiError } from '../api/client';

export function FiestaModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [name, setName] = useState('');
  const [promoStart, setPromoStart] = useState('');
  const [eventDate, setEventDate] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const create = useCreateEvent();

  const canSave = name.trim() && promoStart && eventDate;

  const submit = () => {
    if (!canSave) return;
    setError(null);
    create.mutate(
      {
        name: name.trim(),
        promo_start: `${promoStart}T00:00:00`,
        event_date: `${eventDate}T00:00:00`,
        notes: notes.trim() || null,
      },
      {
        onSuccess: (ev) => onCreated(ev.id),
        onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
      }
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-1 text-lg font-bold">Nueva fiesta</h2>
        <p className="mb-4 text-xs text-[var(--color-muted)]">
          El <b>inicio de campaña</b> es el corte del semáforo: los DMs anteriores (de otra fiesta)
          no cuentan.
        </p>
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-[var(--color-muted)]">Nombre</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="RGB 09.07 @ tcqlub"
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 outline-none"
            />
          </label>
          <div className="flex gap-3">
            <label className="flex flex-1 flex-col gap-1">
              <span className="text-[var(--color-muted)]">Inicio de campaña</span>
              <input
                type="date"
                value={promoStart}
                onChange={(e) => setPromoStart(e.target.value)}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 outline-none"
              />
            </label>
            <label className="flex flex-1 flex-col gap-1">
              <span className="text-[var(--color-muted)]">Fecha del evento</span>
              <input
                type="date"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 outline-none"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-[var(--color-muted)]">Notas (opcional)</span>
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 outline-none"
            />
          </label>
          {error && <p className="text-xs text-[var(--color-red)]">{error}</p>}
          <div className="mt-1 flex justify-end gap-2">
            <button onClick={onClose} className="rounded-lg px-3 py-2 text-[var(--color-muted)]">
              Cancelar
            </button>
            <button
              onClick={submit}
              disabled={!canSave || create.isPending}
              className="rounded-lg bg-[var(--color-green)] px-4 py-2 font-semibold text-[var(--color-bg)] disabled:opacity-40"
            >
              {create.isPending ? 'Creando…' : 'Crear fiesta'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
