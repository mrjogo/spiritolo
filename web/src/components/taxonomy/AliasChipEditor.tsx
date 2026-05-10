import { useEffect, useRef, useState } from 'react';

interface Props {
  value: string[];
  onSave: (next: string[]) => Promise<void> | void;
  onError?: (e: unknown) => void;
  /** Render the chip-input directly, no view-mode/pencil dance.
   *  Each chip add/remove fires onSave eagerly so a controlled
   *  parent (e.g. react-hook-form) stays in sync. */
  alwaysEdit?: boolean;
  /** Inline label rendered in the label column above the chips. Matches
   *  EditableField's right-aligned small-caps Cinzel style. */
  label?: string;
  /** Read-only: render chips with no click-to-edit affordance. Used by the
   *  hover-mode card. */
  readOnly?: boolean;
}

// Match EditableField's grid for visual alignment. minmax(0, 1fr) on the
// value column so chip + input intrinsic widths can't blow out the row.
const LABEL_BASIS = 132;
const COL_GAP = 18;

const LABEL_STYLE: React.CSSProperties = {
  fontFamily: "'Cinzel', serif",
  fontSize: 10,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  opacity: 0.7,
  textAlign: 'right',
  whiteSpace: 'nowrap',
  alignSelf: 'center',
  paddingTop: 6, paddingBottom: 6,
};

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: 0,
  display: 'grid',
  gridTemplateColumns: `${LABEL_BASIS}px minmax(0, 1fr)`,
  columnGap: COL_GAP,
  rowGap: 0,
  alignItems: 'baseline',
  width: '100%',
  background: 'transparent',
  textAlign: 'left',
  font: 'inherit',
  color: 'inherit',
  border: 'none',
};

// Chip cell. The hover/edit outline + background live HERE — not on the
// row — so the visual edit box wraps the chips only, never the label.
// position: relative anchors the pencil-hint affordance.
const CHIPS_CELL_STYLE: React.CSSProperties = {
  position: 'relative',
  gridColumn: 2,
  display: 'flex',
  flexWrap: 'wrap',
  gap: 6,
  alignItems: 'center',
  minHeight: 32,
  minWidth: 0,
  padding: '6px 8px',
  borderWidth: 1,
  borderStyle: 'solid',
  borderColor: 'transparent',
  borderRadius: 'var(--tx-form-radius)',
  background: 'transparent',
};

function PencilHint() {
  return (
    <span
      aria-hidden
      style={{
        position: 'absolute',
        top: 4, right: 6,
        fontSize: 11, lineHeight: 1,
        color: 'var(--tx-brown-soft)',
        opacity: 0.65,
        pointerEvents: 'none',
      }}
    >
      ✎
    </span>
  );
}
const CHIPS_CELL_HOVER_STYLE: React.CSSProperties = {
  borderColor: 'var(--tx-form-border)',
};
const CHIPS_CELL_EDIT_STYLE: React.CSSProperties = {
  borderColor: 'var(--tx-form-border-focus)',
  background: '#fff',
};

export function AliasChipEditor({ value, onSave, onError, alwaysEdit = false, label, readOnly }: Props) {
  if (alwaysEdit) {
    return <ChipInput value={value} onSave={onSave} onError={onError} />;
  }
  return <InlineEditor value={value} onSave={onSave} onError={onError} label={label} readOnly={readOnly} />;
}

/** Always-edit, controlled chip input. Looks like a .tx-input. */
function ChipInput({ value, onSave, onError }: Omit<Props, 'alwaysEdit'>) {
  const [input, setInput] = useState('');

  async function commit(next: string[]) {
    try {
      await onSave(next);
    } catch (e) {
      onError?.(e);
    }
  }

  function addCurrent() {
    const trimmed = input.trim();
    if (trimmed === '' || value.includes(trimmed)) return;
    setInput('');
    void commit([...value, trimmed]);
  }

  function remove(i: number) {
    void commit(value.filter((_, idx) => idx !== i));
  }

  return (
    <div className="tx-input-chips">
      {value.map((a, i) => (
        <span key={`${a}-${i}`} className="tx-chip">
          {a}
          <button
            type="button"
            aria-label={`remove ${a}`}
            onClick={() => remove(i)}
            className="tx-chip__remove"
          >×</button>
        </span>
      ))}
      <input
        type="text"
        className="tx-input-chips__input"
        value={input}
        placeholder="add alias"
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            addCurrent();
          } else if (e.key === 'Tab' && input.trim() !== '') {
            // Commit and stay focused. Empty input → fall through to default
            // tab navigation so focus moves to the next form field.
            e.preventDefault();
            addCurrent();
          } else if (e.key === 'Backspace' && input === '' && value.length > 0) {
            e.preventDefault();
            remove(value.length - 1);
          }
        }}
      />
    </div>
  );
}

/** Original inline view-mode-with-pencil editor used by NodeCard. */
function InlineEditor({ value, onSave, onError, label, readOnly }: Omit<Props, 'alwaysEdit'>) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>(value);
  const [input, setInput] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  async function commit() {
    setEditing(false);
    setInput('');
    if (arraysEqual(draft, value)) return;
    try {
      await onSave(draft);
    } catch (e) {
      setDraft(value);
      onError?.(e);
    }
  }

  function addCurrent() {
    const trimmed = input.trim();
    if (trimmed === '' || draft.includes(trimmed)) return;
    setDraft([...draft, trimmed]);
    setInput('');
  }

  function remove(i: number) {
    setDraft(draft.filter((_, idx) => idx !== i));
    inputRef.current?.focus();
  }

  if (editing) {
    return (
      <div
        ref={containerRef}
        style={ROW_STYLE}
        onBlur={(e) => {
          if (containerRef.current && !containerRef.current.contains(e.relatedTarget as Node | null)) {
            void commit();
          }
        }}
      >
        {label && <span style={LABEL_STYLE}>{label}</span>}
        <div style={{ ...CHIPS_CELL_STYLE, ...CHIPS_CELL_EDIT_STYLE }}>
          {draft.map((a, i) => (
            <span key={`${a}-${i}`} className="tx-chip">
              {a}
              <button
                type="button"
                aria-label={`remove ${a}`}
                onClick={() => remove(i)}
                className="tx-chip__remove"
              >×</button>
            </span>
          ))}
          <input
            ref={inputRef}
            type="text"
            value={input}
            placeholder="+ add alias"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addCurrent();
              } else if (e.key === 'Tab' && input.trim() !== '') {
                e.preventDefault();
                addCurrent();
              } else if (e.key === 'Escape') {
                // First Esc cancels editing; don't propagate to NodeCard's
                // window-level Escape handler (which would unfocus the node).
                e.stopPropagation();
                setDraft(value);
                setInput('');
                setEditing(false);
              }
            }}
            style={{
              font: 'inherit',
              color: 'inherit',
              background: 'transparent',
              border: 'none',
              outline: 'none',
              flex: '1 1 60px',
              minWidth: 60,
              fontSize: 13,
            }}
          />
        </div>
      </div>
    );
  }

  const chipsContent = value.length === 0
    ? <span style={{ fontStyle: 'italic', opacity: 0.6 }}>—</span>
    : value.map((a) => <span key={a} className="tx-chip">{a}</span>);

  if (readOnly) {
    return (
      <div style={ROW_STYLE} aria-label={label ?? 'aliases'}>
        {label && <span style={LABEL_STYLE}>{label}</span>}
        <div style={CHIPS_CELL_STYLE}>{chipsContent}</div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={label ? `edit ${label}` : 'edit aliases'}
      style={{ ...ROW_STYLE, cursor: 'pointer' }}
    >
      {label && <span style={LABEL_STYLE}>{label}</span>}
      <div style={{ ...CHIPS_CELL_STYLE, ...(hover ? CHIPS_CELL_HOVER_STYLE : {}) }}>
        {chipsContent}
        {hover && <PencilHint />}
      </div>
    </button>
  );
}

function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
