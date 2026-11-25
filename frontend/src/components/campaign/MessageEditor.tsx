import { hasLink } from './types';

/** The message variants editor (left column, top). */
export function MessageEditor({
  templates,
  setTemplates,
  includeLink,
  setIncludeLink,
}: {
  templates: string[];
  setTemplates: (t: string[]) => void;
  includeLink: boolean;
  setIncludeLink: (v: boolean) => void;
}) {
  const variants = templates.filter((t) => t.trim());
  const usesName = variants.some((t) => /\{nombre\}|\{usuario\}|\{username\}/.test(t));
  const linkPresent = variants.some(hasLink);

  return (
    <div className="flex flex-col gap-2">
      <span className="text-muted">
        Mensaje ({variants.length} versi{variants.length === 1 ? 'ón' : 'ones'}).{' '}
        <code>{'{nombre}'}</code> y <code>{'{usuario}'}</code> se cambian por los de cada persona.
        Escribí 2 o 3 versiones: si todos reciben el mismo texto, Instagram lo ve como spam.
      </span>
      {templates.map((t, i) => (
        <textarea
          key={i}
          value={t}
          onChange={(e) => {
            const next = [...templates];
            next[i] = e.target.value;
            setTemplates(next);
          }}
          rows={2}
          aria-label={i === 0 ? 'Mensaje principal' : `Otra versión del mensaje ${i + 1}`}
          placeholder={i === 0 ? 'Mensaje principal…' : 'Otra versión (opcional)…'}
          className="w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 outline-none"
        />
      ))}
      {variants.length > 0 && !usesName && (
        <p className="text-xs text-yellow">
          ⚠ Sin <code>{'{nombre}'}</code> todos reciben exactamente el mismo texto: más pinta de
          spam.
        </p>
      )}
      {linkPresent && (
        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={includeLink}
            onChange={(e) => setIncludeLink(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">Incluir el link en el DM</span>
            <span className={`block ${includeLink ? 'text-yellow' : 'text-muted'}`}>
              {includeLink
                ? '⚠ Un link en el primer mensaje es lo que más hace que Instagram bloquee. Más seguro: destildalo y mandá el link cuando te contesten.'
                : 'El DM sale sin el link. Mandalo cuando te contesten.'}
            </span>
          </span>
        </label>
      )}
    </div>
  );
}
