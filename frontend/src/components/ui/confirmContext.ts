import { createContext, useContext, type ReactNode } from 'react';

/** In-app replacement for window.confirm(): same look as every other modal,
 * keyboard accessible (Escape = cancel), and awaitable:
 *
 *   const confirm = useConfirm();
 *   if (!(await confirm({ title: '¿Desconectar?', message: '…' }))) return;
 *
 * Rendered by <ConfirmProvider> (ConfirmDialog.tsx), mounted once in main.tsx. */
export type ConfirmOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red confirm button for destructive or risky actions. */
  danger?: boolean;
};

export const ConfirmContext = createContext<((opts: ConfirmOptions) => Promise<boolean>) | null>(
  null
);

export function useConfirm(): (opts: ConfirmOptions) => Promise<boolean> {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error('useConfirm must be used inside <ConfirmProvider>');
  return confirm;
}
