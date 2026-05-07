import { useEffect } from 'react';

interface Props {
  message: string;
  kind?: 'info' | 'error';
  onDismiss: () => void;
}

export function Toast({ message, kind = 'info', onDismiss }: Props) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 4000);
    return () => clearTimeout(t);
  }, [onDismiss]);
  return (
    <div
      role="status"
      style={{
        position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
        background: kind === 'error' ? '#3a1818' : '#2a1f10',
        color: '#f8f0d8',
        border: '1px solid ' + (kind === 'error' ? '#b04040' : '#8b6f3a'),
        padding: '8px 14px', borderRadius: 4, fontSize: 12,
        fontFamily: "'Cinzel', serif", letterSpacing: '0.1em',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        zIndex: 200,
      }}
    >
      {message}
    </div>
  );
}
