import { useSyncExternalStore } from 'react';

/** A short, neutral message shown as a toast (not an error), e.g. a job whose
 * outcome we could not follow. Lives in memory only. */
export type Notice = { id: number; kind: string; text: string };

const SHOW_MS = 7000; // same as a finished task's toast

let notices: readonly Notice[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function set(next: readonly Notice[]) {
  notices = next;
  for (const l of listeners) l();
}

/** Close a notice now (its ✕), instead of waiting for it to go away. */
export function dismissNotice(id: number): void {
  if (notices.some((n) => n.id === id)) set(notices.filter((n) => n.id !== id));
}

/** Show a notice for a few seconds. `kind` is the job kind it is about (or
 * another kind known to lib/jobs, e.g. 'export'). */
export function notify(kind: string, text: string): void {
  const id = nextId++;
  set([...notices, { id, kind, text }]);
  setTimeout(() => dismissNotice(id), SHOW_MS);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useNotices(): readonly Notice[] {
  return useSyncExternalStore(subscribe, () => notices);
}
