import { useEffect } from 'react';

interface Props {
  onBackdropClick: () => void;
  children: React.ReactNode;
}

// Backdrop + Esc-to-close shell shared by every modal in the app
// (CreateChildModal, DeleteNodeModal, EditParentsModal, and — new in /ops —
// CostConfirmModal). Lifted out of taxonomy/CreateChildModal.tsx so it can be
// composed from anywhere, not just the taxonomy page.
export function ModalShell({ onBackdropClick, children }: Props) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onBackdropClick(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onBackdropClick]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => { if (e.target === e.currentTarget) onBackdropClick(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(42, 31, 16, 0.92)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div className="tx-modal">{children}</div>
    </div>
  );
}
