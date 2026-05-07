import { useEffect, useRef, useState } from 'react';

type Props =
  | TextProps
  | DropdownProps
  | ToggleProps;

interface BaseProps {
  label: string;
  onError?: (e: unknown) => void;
}

interface TextProps extends BaseProps {
  kind: 'text';
  value: string;
  onSave: (next: string) => Promise<void> | void;
}

interface DropdownProps extends BaseProps {
  kind: 'dropdown';
  value: string;
  options: { value: string; label: string }[];
  onSave: (next: string) => Promise<void> | void;
}

interface ToggleProps extends BaseProps {
  kind: 'toggle';
  value: boolean;
  onSave: (next: boolean) => Promise<void> | void;
}

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: '2px 6px',
  borderWidth: 1,
  borderStyle: 'solid',
  borderColor: 'transparent',
  borderRadius: 'var(--tx-form-radius)',
};
const ROW_HOVER_STYLE: React.CSSProperties = {
  borderColor: 'var(--tx-form-border)',
};

export function EditableField(props: Props) {
  if (props.kind === 'text') return <TextField {...props} />;
  if (props.kind === 'dropdown') return <DropdownField {...props} />;
  return <ToggleField {...props} />;
}

function TextField({ label, value, onSave, onError }: TextProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    try {
      await onSave(next);
    } catch (e) {
      setDraft(value);
      onError?.(e);
    }
  }

  if (editing) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit(draft);
            else if (e.key === 'Escape') {
              setDraft(value);
              setEditing(false);
            }
          }}
          onBlur={() => void commit(draft)}
          style={{ width: '100%', font: 'inherit', color: 'inherit', background: 'transparent', border: 'none' }}
        />
      </div>
    );
  }

  return (
    <div
      style={{ ...ROW_STYLE, ...(hover ? ROW_HOVER_STYLE : {}) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={label}
    >
      {value}
      <button
        type="button"
        aria-label={`edit ${label}`}
        onClick={() => setEditing(true)}
        style={{
          position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
          background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--tx-brown-soft)',
          padding: 0, lineHeight: 1, fontSize: 13,
          opacity: hover ? 1 : 0,
        }}
      >
        ✎
      </button>
    </div>
  );
}

function DropdownField({ label, value, options, onSave, onError }: DropdownProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    try {
      await onSave(next);
    } catch (e) {
      onError?.(e);
    }
  }

  if (editing) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <select
          autoFocus
          defaultValue={value}
          onChange={(e) => void commit(e.target.value)}
          onBlur={() => setEditing(false)}
          onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false); }}
          style={{ font: 'inherit', color: 'inherit', background: 'transparent' }}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div
      style={{ ...ROW_STYLE, ...(hover ? ROW_HOVER_STYLE : {}) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={label}
    >
      {options.find((o) => o.value === value)?.label ?? value}
      <button
        type="button"
        aria-label={`edit ${label}`}
        onClick={() => setEditing(true)}
        style={{
          position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
          background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--tx-brown-soft)',
          padding: 0, lineHeight: 1, fontSize: 13,
          opacity: hover ? 1 : 0,
        }}
      >
        ✎
      </button>
    </div>
  );
}

function ToggleField({ label, value, onSave, onError }: ToggleProps) {
  const [pending, setPending] = useState(false);
  return (
    <div style={ROW_STYLE} aria-label={label}>
      <button
        type="button"
        className="tx-toggle"
        role="switch"
        aria-checked={value}
        disabled={pending}
        onClick={async () => {
          setPending(true);
          try {
            await onSave(!value);
          } catch (e) {
            onError?.(e);
          } finally {
            setPending(false);
          }
        }}
        style={{ height: 'auto', padding: 0 }}
      >
        <span className="tx-toggle__track">
          <span className="tx-toggle__thumb" />
        </span>
      </button>
    </div>
  );
}
