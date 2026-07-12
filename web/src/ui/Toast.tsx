import { useEffect } from 'react';

export type ToastKind = 'info' | 'error' | 'progress';

interface Props {
  message: string;
  kind?: ToastKind;
  onDismiss: () => void;
  /** When true, the toast does not auto-dismiss after 4s. The caller
   *  controls when to clear it. Used for in-progress states whose end is
   *  signaled by the application, not by a timer. */
  persist?: boolean;
}

export function Toast({ message, kind = 'info', onDismiss, persist = false }: Props) {
  useEffect(() => {
    if (persist) return;
    const t = setTimeout(onDismiss, 4000);
    return () => clearTimeout(t);
  }, [onDismiss, persist]);
  const border =
    kind === 'error' ? '#b04040'
    : kind === 'progress' ? '#a78a4a'
    : '#8b6f3a';
  const bg =
    kind === 'error' ? '#3a1818'
    : kind === 'progress' ? '#1f1808'
    : '#2a1f10';
  return (
    <div
      role="status"
      style={{
        position: 'fixed', bottom: 24, right: 24,
        background: bg,
        color: '#f8f0d8',
        border: `1px solid ${border}`,
        padding: '8px 14px', borderRadius: 4, fontSize: 12,
        fontFamily: "'Cinzel', serif", letterSpacing: '0.1em',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        zIndex: 200,
        display: 'flex', alignItems: 'center', gap: 8,
      }}
    >
      {kind === 'progress' && (
        <span
          aria-hidden
          style={{
            width: 10, height: 10, borderRadius: '50%',
            border: '1.5px solid #a78a4a', borderTopColor: 'transparent',
            animation: 'taxonomy-spin 0.9s linear infinite',
            display: 'inline-block', flex: '0 0 auto',
          }}
        />
      )}
      <span>{message}</span>
    </div>
  );
}
