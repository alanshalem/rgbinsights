import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Shared modal shell: dimmed overlay + panel. `center` for short dialogs,
 * default is top-aligned + scrollable for tall content.
 *
 * Closes on Escape, or on a genuine backdrop click — a press that both STARTS
 * and ENDS on the overlay. Selecting text inside and releasing outside (a
 * drag-out) does NOT close it, so copying a message never loses your work.
 *
 * Keyboard: focus moves into the dialog on open, Tab / Shift+Tab stay inside
 * it, and on close focus goes back to whatever opened it.
 *
 * Rendered through a portal to <body>: a `fixed` element is positioned relative
 * to the nearest ancestor with a transform/filter, and the navbar uses
 * `backdrop-blur`, which would otherwise pin the modal to the navbar. */
export function Modal({
  onClose,
  children,
  label,
  size = 'md',
  center = false,
}: {
  onClose: () => void;
  children: ReactNode;
  /** Accessible name of the dialog (what a screen reader announces). */
  label: string;
  size?: 'md' | 'lg' | 'xl';
  center?: boolean;
}) {
  const pressedBackdrop = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);
  // What had focus when the modal opened (read on the first render, before an
  // autoFocus field inside takes it), to give focus back on close.
  const [opener] = useState(() =>
    document.activeElement instanceof HTMLElement ? document.activeElement : null
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !panelRef.current) return;
      // Keep Tab inside the dialog: wrap from the last control to the first.
      const items = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) {
        e.preventDefault();
        return;
      }
      const inside = panelRef.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Move focus into the dialog on open (unless a field inside already took it
  // with autoFocus), so keyboard/screen-reader users land inside it; give it
  // back to the opener on close.
  useEffect(() => {
    if (!panelRef.current?.contains(document.activeElement)) panelRef.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [opener]);

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
        aria-label={label}
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
