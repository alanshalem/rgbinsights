import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const INTERACTIVE = 'a, button, select, summary, label, [role="button"]';

/** Signature cursor: a precise center dot + a ring that trails with easing and
 * echoes the wordmark's red/blue aberration. Desktop + motion-ok only; disables
 * itself (native cursor) on touch or prefers-reduced-motion. */
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
    let raf = 0;

    const place = (el: HTMLDivElement | null, x: number, y: number) => {
      if (el) el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
    };
    const onMove = (e: MouseEvent) => {
      pos.x = e.clientX;
      pos.y = e.clientY;
      place(dotRef.current, pos.x, pos.y); // dot is exact (precision preserved)
      if (dotRef.current) dotRef.current.style.opacity = '1';
      if (ringRef.current) ringRef.current.style.opacity = '1';
      const hovering = (e.target as HTMLElement)?.closest?.(INTERACTIVE);
      ringRef.current?.classList.toggle('is-hover', !!hovering);
    };
    const onDown = () => ringRef.current?.classList.add('is-down');
    const onUp = () => ringRef.current?.classList.remove('is-down');
    const loop = () => {
      ring.x += (pos.x - ring.x) * 0.2; // trails with easing
      ring.y += (pos.y - ring.y) * 0.2;
      place(ringRef.current, ring.x, ring.y);
      raf = requestAnimationFrame(loop);
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mousedown', onDown);
    window.addEventListener('mouseup', onUp);
    raf = requestAnimationFrame(loop);
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
