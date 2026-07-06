import type { ReactNode } from 'react';

/** Wraps content in a link to the Instagram post (new tab) when we have its URL,
 * so a comment/like opens in context. Falls back to plain text otherwise. */
export function PostLink({
  url,
  title,
  className,
  children,
}: {
  url: string | null | undefined;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  if (!url) return <span className={className}>{children}</span>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      title={title ?? 'Abrir el post en Instagram'}
      className={className}
    >
      {children}
    </a>
  );
}
