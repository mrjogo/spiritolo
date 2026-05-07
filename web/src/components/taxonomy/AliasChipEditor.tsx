import { useEffect, useRef, useState } from 'react';

interface Props {
  value: string[];
  onSave: (next: string[]) => Promise<void> | void;
  onError?: (e: unknown) => void;
  /** Render the chip-input directly, no view-mode/pencil dance.
   *  Each chip add/remove fires onSave eagerly so a controlled
   *  parent (e.g. react-hook-form) stays in sync. */
  alwaysEdit?: boolean;
}

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: '4px 6px',
  borderWidth: 1,
  borderStyle: 'solid',
  borderColor: 'transparent',
  borderRadius: 'var(--tx-form-radius)',
  display: 'flex',
  flexWrap: 'wrap',
  gap: 6,
  alignItems: 'center',
  minHeight: 32,
};
const HOVER_STYLE: React.CSSProperties = { borderColor: 'var(--tx-form-border)' };

export function AliasChipEditor({ value, onSave, onError, alwaysEdit = false }: Props) {
  if (alwaysEdit) {
    return <ChipInput value={value} onSave={onSave} onError={onError} />;
  }
  return <InlineEditor value={value} onSave={onSave} onError={onError} />;
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
function InlineEditor({ value, onSave, onError }: Omit<Props, 'alwaysEdit'>) {
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
        style={{ ...ROW_STYLE, ...HOVER_STYLE, background: 'var(--tx-form-bg)' }}
        onBlur={(e) => {
          if (containerRef.current && !containerRef.current.contains(e.relatedTarget as Node | null)) {
            void commit();
          }
        }}
      >
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
            flex: '1 1 80px',
            minWidth: 80,
            fontSize: 13,
          }}
        />
      </div>
    );
  }

  return (
    <div
      style={{ ...ROW_STYLE, ...(hover ? HOVER_STYLE : {}) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {value.length === 0
        ? <span style={{ fontStyle: 'italic', opacity: 0.6 }}>—</span>
        : value.map((a) => <span key={a} className="tx-chip">{a}</span>)}
      <button
        type="button"
        aria-label="edit aliases"
        onClick={() => setEditing(true)}
        style={{
          position: 'absolute', right: 6, top: 6,
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--tx-brown-soft)', padding: 0, lineHeight: 1, fontSize: 13,
          opacity: hover ? 1 : 0,
        }}
      >✎</button>
    </div>
  );
}

function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
