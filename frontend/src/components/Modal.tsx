import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

/** Shared modal shell: dimmed overlay + panel. `center` for short dialogs,
 * default is top-aligned + scrollable for tall content.
 *
 * Rendered through a portal to <body>: a `fixed` element is positioned relative
 * to the nearest ancestor with a transform/filter, and the navbar uses
 * `backdrop-blur`, which would otherwise pin the modal to the navbar. */
export function Modal({
  onClose,
  children,
  size = 'md',
  center = false,
}: {
  onClose: () => void;
  children: ReactNode;
  size?: 'md' | 'lg';
  center?: boolean;
}) {
  const width = size === 'lg' ? 'max-w-2xl' : 'max-w-md';
  const outer = center ? 'items-center' : 'overflow-y-auto';
  const panel = center ? 'p-5' : 'my-8 h-fit p-6';
  return createPortal(
    <div
      className={`fixed inset-0 z-50 flex justify-center bg-black/60 p-4 ${outer}`}
      onClick={onClose}
    >
      <div
        className={`w-full ${width} rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] ${panel}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body
  );
}
