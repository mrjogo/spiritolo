import { useEffect, useRef, useState } from 'react';

interface Props {
  value: string[];
  onSave: (next: string[]) => Promise<void> | void;
  onError?: (e: unknown) => void;
}

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: '2px 6px',
  border: '1px solid transparent',
  borderRadius: 3,
  display: 'flex',
  flexWrap: 'wrap',
  gap: 4,
  alignItems: 'center',
};
const HOVER_STYLE: React.CSSProperties = { borderColor: '#8b6f3a' };

const CHIP_STYLE: React.CSSProperties = {
  background: '#faf5e6',
  border: '1px solid #b8924d',
  borderRadius: 10,
  padding: '1px 6px',
  fontSize: 11,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
};

export function AliasChipEditor({ value, onSave, onError }: Props) {
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
    // Keep focus inside the editor so the container's onBlur doesn't fire prematurely
    inputRef.current?.focus();
  }

  if (editing) {
    return (
      <div
        ref={containerRef}
        style={{ ...ROW_STYLE, ...HOVER_STYLE }}
        onBlur={(e) => {
          // Only save if focus is leaving the whole editor
          if (containerRef.current && !containerRef.current.contains(e.relatedTarget as Node | null)) {
            void commit();
          }
        }}
      >
        {draft.map((a, i) => (
          <span key={`${a}-${i}`} style={CHIP_STYLE}>
            {a}
            <button
              type="button"
              aria-label={`remove ${a}`}
              onClick={() => remove(i)}
              style={{ background: 'transparent', border: 'none', color: '#c44', cursor: 'pointer', fontSize: 12, padding: 0, lineHeight: 1 }}
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
            } else if (e.key === 'Escape') {
              setDraft(value);
              setInput('');
              setEditing(false);
            }
          }}
          style={{ font: 'inherit', color: 'inherit', background: 'transparent', border: 'none', flex: '1 1 80px', minWidth: 80 }}
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
        : value.map((a) => <span key={a} style={CHIP_STYLE}>{a}</span>)}
      <button
        type="button"
        aria-label="edit aliases"
        onClick={() => setEditing(true)}
        style={{
          position: 'absolute', right: 4, top: 2,
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: '#8b6f3a', padding: 0, lineHeight: 1, fontSize: 13,
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
