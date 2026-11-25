/** Why an Instagram action is disabled: another job is using Instagram (the app
 * runs one at a time to look human). Visible text, not a hover-only tooltip. */
export function JobBusyNote() {
  return (
    <p className="mt-2 text-xs text-yellow">
      Hay una tarea de Instagram en curso (abajo a la derecha). Esperá que termine.
    </p>
  );
}
