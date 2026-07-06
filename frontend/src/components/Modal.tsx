import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/** Shared modal shell: dimmed overlay + panel. `center` for short dialogs,
 * default is top-aligned + scrollable for tall content.
 *
 * Closes on Escape, or on a genuine backdrop click — a press that both STARTS
 * and ENDS on the overlay. Selecting text inside and releasing outside (a
 * drag-out) does NOT close it, so copying a message never loses your work.
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
  size?: 'md' | 'lg' | 'xl';
  center?: boolean;
}) {
  const pressedBackdrop = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Move focus into the dialog on open, so keyboard/screen-reader users land
  // inside it (and Escape works without clicking first).
  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  const width = size === 'xl' ? 'max-w-4xl' : size === 'lg' ? 'max-w-2xl' : 'max-w-md';
  const outer = center ? 'items-center' : 'overflow-y-auto';
  const panel = center ? 'p-5' : 'my-8 h-fit p-6';
  return createPortal(
    <div
      className={`fixed inset-0 z-50 flex justify-center bg-black/70 p-4 backdrop-blur-sm ${outer}`}
      onMouseDown={(e) => {
        pressedBackdrop.current = e.target === e.currentTarget;
      }}
      onMouseUp={(e) => {
        if (pressedBackdrop.current && e.target === e.currentTarget) onClose();
        pressedBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={`anim-pop w-full ${width} rounded-2xl border border-border bg-panel shadow-2xl shadow-black/40 outline-none ${panel}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body
  );
}
