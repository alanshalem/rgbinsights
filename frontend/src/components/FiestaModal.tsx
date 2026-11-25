import { useState, type FormEvent } from 'react';
import { useCreateEvent } from '../api/hooks';
import { ApiError } from '../api/client';
import { Modal } from './ui/Modal';

const FIELD_CLS = 'rounded-lg border border-border bg-bg px-3 py-2 outline-none focus:border-muted';

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

  // Both are yyyy-mm-dd, so comparing the strings compares the dates.
  const datesBackwards = Boolean(promoStart && eventDate && eventDate < promoStart);
  const canSave = Boolean(name.trim() && promoStart && eventDate && !datesBackwards);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSave || create.isPending) return;
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
        onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
      }
    );
  };

  return (
    <Modal onClose={onClose} center label="Nueva fiesta">
      <h2 className="display mb-1 text-lg font-black tracking-tight uppercase">Nueva fiesta</h2>
      <p className="mb-4 text-xs text-muted">
        El semáforo de la fiesta cuenta los DMs <b>desde el inicio de la promo</b>: lo que hablaste
        antes (por otra fiesta) no cuenta.
      </p>
      <form onSubmit={submit} className="flex flex-col gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-muted">Nombre</span>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="RGB 09.07 @ tcqlub"
            className={FIELD_CLS}
          />
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-muted">Inicio de la promo</span>
            <input
              type="date"
              value={promoStart}
              onChange={(e) => setPromoStart(e.target.value)}
              aria-describedby="promo-hint"
              className={FIELD_CLS}
            />
            <span id="promo-hint" className="text-xs text-muted">
              El día que empezaste a publicar esta fiesta
            </span>
          </label>
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-muted">Fecha de la fiesta</span>
            <input
              type="date"
              value={eventDate}
              min={promoStart || undefined}
              onChange={(e) => setEventDate(e.target.value)}
              aria-invalid={datesBackwards}
              aria-describedby={datesBackwards ? 'date-error' : undefined}
              className={`${FIELD_CLS} ${datesBackwards ? 'border-red' : ''}`}
            />
          </label>
        </div>
        {datesBackwards && (
          <p id="date-error" role="alert" className="text-xs text-red">
            La fiesta no puede ser antes del inicio de la promo.
          </p>
        )}
        <label className="flex flex-col gap-1">
          <span className="text-muted">Notas (opcional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} className={FIELD_CLS} />
        </label>
        {error && (
          <p role="alert" className="text-xs text-red">
            No se pudo crear la fiesta: {error}
          </p>
        )}
        <div className="mt-1 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-muted">
            Cancelar
          </button>
          <button
            type="submit"
            disabled={!canSave || create.isPending}
            className="rounded-lg bg-green px-4 py-2 font-semibold text-bg disabled:opacity-40"
          >
            {create.isPending ? 'Creando…' : 'Crear fiesta'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
