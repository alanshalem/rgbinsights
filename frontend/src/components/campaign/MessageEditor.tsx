/** The message variants editor (left column, top). */
export function MessageEditor({
  templates,
  setTemplates,
}: {
  templates: string[];
  setTemplates: (t: string[]) => void;
}) {
  const variants = templates.filter((t) => t.trim());
  const usesName = variants.some((t) => /\{nombre\}|\{usuario\}|\{username\}/.test(t));

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
    </div>
  );
}
