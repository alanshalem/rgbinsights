import { AUDIENCE, type Audience } from './types';

/** Follow-status audience filter (left column, middle). */
export function AudiencePicker({
  audience,
  setAudience,
}: {
  audience: Audience;
  setAudience: (a: Audience) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-muted">¿A quién le mando?</span>
      {AUDIENCE.map((a) => (
        <label
          key={a.key}
          className={`flex cursor-pointer gap-2 rounded-lg border px-3 py-2 ${
            audience === a.key ? 'border-blue bg-blue/10' : 'border-border'
          }`}
        >
          <input
            type="radio"
            name="audience"
            checked={audience === a.key}
            onChange={() => setAudience(a.key)}
            className="mt-0.5"
          />
          <span>
            <span className="font-semibold">{a.label}</span>
            <span className="block text-xs text-muted">{a.hint}</span>
          </span>
        </label>
      ))}
    </div>
  );
}
