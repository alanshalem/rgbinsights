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
        Mensaje ({variants.length} variante{variants.length === 1 ? '' : 's'}) — usá{' '}
        <code>{'{nombre}'}</code> y <code>{'{usuario}'}</code>. Varias variantes = menos spam.
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
          placeholder={i === 0 ? 'Mensaje principal…' : 'Variante (opcional)…'}
          className="w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 outline-none"
        />
      ))}
      {variants.length > 0 && !usesName && (
        <p className="text-xs text-yellow">
          ⚠ Sin <code>{'{nombre}'}</code> todos reciben el mismo texto exacto — más señal de spam.
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
          <span className={includeLink ? 'text-yellow' : 'text-muted'}>
            {includeLink ? (
              <>
                ⚠ Incluir el link en el DM. Los links en el primer contacto disparan el bloqueo. Lo
                más seguro: destildá esto y mandá el link cuando te respondan.
              </>
            ) : (
              <>El DM va sin link (contacto inicial). Tildá para incluirlo (más riesgo).</>
            )}
          </span>
        </label>
      )}
    </div>
  );
}
