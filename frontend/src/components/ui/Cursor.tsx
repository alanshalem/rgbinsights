import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const INTERACTIVE = 'a, button, select, summary, label, [role="button"]';
// Inside dialogs and forms the native cursor is back (index.css): precise
// clicking and typing matter more there than the flourish.
const NATIVE = '[role="dialog"], form';

/** Signature cursor: a precise center dot + a ring that trails with easing and
 * echoes the wordmark's red/blue aberration. Desktop + motion-ok only; disables
 * itself (native cursor) on touch or prefers-reduced-motion, and hides over
 * modals and forms, where the native cursor shows instead. */
export function Cursor() {
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);

  useEffect(() => {
    const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const motionOk = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!fine || !motionOk) return;

    setOn(true);
    document.documentElement.classList.add('custom-cursor');

    const pos = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const ring = { x: pos.x, y: pos.y };
    let raf = 0; // 0 = idle (no frame scheduled)

    const place = (el: HTMLDivElement | null, x: number, y: number) => {
      if (el) el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
    };
    const onMove = (e: MouseEvent) => {
      pos.x = e.clientX;
      pos.y = e.clientY;
      place(dotRef.current, pos.x, pos.y); // dot is exact (precision preserved)
      const target = e.target as HTMLElement | null;
      const shown = target?.closest?.(NATIVE) ? '0' : '1';
      if (dotRef.current) dotRef.current.style.opacity = shown;
      if (ringRef.current) ringRef.current.style.opacity = shown;
      const hovering = target?.closest?.(INTERACTIVE);
      ringRef.current?.classList.toggle('is-hover', !!hovering);
      wake();
    };
    const onDown = () => ringRef.current?.classList.add('is-down');
    const onUp = () => ringRef.current?.classList.remove('is-down');
    // Animate only while the ring is catching up; once it reaches the pointer it
    // snaps (sub-pixel, invisible) and the loop stops until the next move.
    const loop = () => {
      ring.x += (pos.x - ring.x) * 0.2; // trails with easing
      ring.y += (pos.y - ring.y) * 0.2;
      const settled = Math.abs(pos.x - ring.x) < 0.1 && Math.abs(pos.y - ring.y) < 0.1;
      if (settled) {
        ring.x = pos.x;
        ring.y = pos.y;
      }
      place(ringRef.current, ring.x, ring.y);
      raf = settled ? 0 : requestAnimationFrame(loop);
    };
    const wake = () => {
      if (raf === 0) raf = requestAnimationFrame(loop);
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mousedown', onDown);
    window.addEventListener('mouseup', onUp);
    wake();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('mouseup', onUp);
      document.documentElement.classList.remove('custom-cursor');
    };
  }, []);

  if (!on) return null;
  // Portal to <body>: keeps the cursor above modals/toasts (which are also
  // body-level portals) instead of trapped inside #root's stacking context.
  return createPortal(
    <>
      <div ref={ringRef} className="cursor-ring" />
      <div ref={dotRef} className="cursor-dot" />
    </>,
    document.body
  );
}
