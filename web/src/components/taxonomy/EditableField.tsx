import { useEffect, useRef, useState } from 'react';

type Props =
  | TextProps
  | DropdownProps
  | ToggleProps;

interface BaseProps {
  label: string;
  onError?: (e: unknown) => void;
  /** When true, render the same row layout as edit mode but disable the
   *  click-to-edit button and toggle interactivity. Used by the hover-mode
   *  card so hover and pinned look identical. */
  readOnly?: boolean;
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

// Two-column grid: right-aligned label, left-aligned value. Labels are
// sized to fit the longest one ("DEFINING GARNISH" at 10px Cinzel) plus
// generous breathing room before the value column. The value column uses
// minmax(0, 1fr) so its content respects the column width — without the
// `0` minimum, intrinsic content widths would force the row wider than
// the card and trigger horizontal overflow.
const LABEL_BASIS = 132;
const COL_GAP = 18;

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: 0,
  display: 'grid',
  gridTemplateColumns: `${LABEL_BASIS}px minmax(0, 1fr)`,
  columnGap: COL_GAP,
  alignItems: 'baseline',
  width: '100%',
  background: 'transparent',
  textAlign: 'left',
  font: 'inherit',
  color: 'inherit',
  border: 'none',
};

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

// Value cell. Padding + (transparent) border live HERE — not on the row —
// so the hover/edit outline only ever wraps the value, never the label.
// `position: relative` anchors the pencil affordance.
const VALUE_CELL_STYLE: React.CSSProperties = {
  position: 'relative',
  textAlign: 'left',
  padding: '6px 8px',
  borderWidth: 1,
  borderStyle: 'solid',
  borderColor: 'transparent',
  borderRadius: 'var(--tx-form-radius)',
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  minWidth: 0,
  background: 'transparent',
};
const VALUE_CELL_HOVER_STYLE: React.CSSProperties = {
  borderColor: 'var(--tx-form-border)',
};
const VALUE_CELL_EDIT_STYLE: React.CSSProperties = {
  borderColor: 'var(--tx-form-border-focus)',
  background: '#fff',
};

const VALUE_TEXT_STYLE: React.CSSProperties = {
  flex: '1 1 auto',
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
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

function Spinner() {
  return (
    <span
      aria-hidden
      style={{
        width: 10, height: 10, borderRadius: '50%',
        border: '1.5px solid var(--tx-form-border)', borderTopColor: 'transparent',
        animation: 'taxonomy-spin 0.9s linear infinite',
        display: 'inline-block', flex: '0 0 auto',
      }}
    />
  );
}

export function EditableField(props: Props) {
  if (props.kind === 'text') return <TextField {...props} />;
  if (props.kind === 'dropdown') return <DropdownField {...props} />;
  return <ToggleField {...props} />;
}

function TextField({ label, value, onSave, onError, readOnly }: TextProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
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
    setPending(true);
    try {
      await onSave(next);
    } catch (e) {
      setDraft(value);
      onError?.(e);
    } finally {
      setPending(false);
    }
  }

  if (readOnly) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <span style={LABEL_STYLE}>{label}</span>
        <span style={VALUE_CELL_STYLE}>
          <span style={VALUE_TEXT_STYLE}>{value}</span>
        </span>
      </div>
    );
  }

  if (editing) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <span style={LABEL_STYLE}>{label}</span>
        <span style={{ ...VALUE_CELL_STYLE, ...VALUE_CELL_EDIT_STYLE }}>
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void commit(draft);
              else if (e.key === 'Escape') {
                e.stopPropagation();
                setDraft(value);
                setEditing(false);
              }
            }}
            onBlur={() => void commit(draft)}
            style={{
              font: 'inherit', color: 'inherit', background: 'transparent',
              border: 'none', outline: 'none', width: '100%', minWidth: 0,
            }}
          />
        </span>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={`edit ${label}`}
      style={{ ...ROW_STYLE, cursor: 'pointer' }}
    >
      <span style={LABEL_STYLE}>{label}</span>
      <span style={{ ...VALUE_CELL_STYLE, ...(hover ? VALUE_CELL_HOVER_STYLE : {}) }}>
        <span style={VALUE_TEXT_STYLE}>{value}</span>
        {pending && <Spinner />}
        {hover && !pending && <PencilHint />}
      </span>
    </button>
  );
}

function DropdownField({ label, value, options, onSave, onError, readOnly }: DropdownProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    setPending(true);
    try {
      await onSave(next);
    } catch (e) {
      onError?.(e);
    } finally {
      setPending(false);
    }
  }

  const displayLabel = options.find((o) => o.value === value)?.label ?? value;

  if (readOnly) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <span style={LABEL_STYLE}>{label}</span>
        <span style={VALUE_CELL_STYLE}>
          <span style={VALUE_TEXT_STYLE}>{displayLabel}</span>
        </span>
      </div>
    );
  }

  if (editing) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <span style={LABEL_STYLE}>{label}</span>
        <span style={{ ...VALUE_CELL_STYLE, ...VALUE_CELL_EDIT_STYLE }}>
          <select
            autoFocus
            defaultValue={value}
            onChange={(e) => void commit(e.target.value)}
            onBlur={() => setEditing(false)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.stopPropagation();
                setEditing(false);
              }
            }}
            style={{
              font: 'inherit', color: 'inherit', background: 'transparent',
              border: 'none', outline: 'none', width: '100%', minWidth: 0,
            }}
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </span>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={`edit ${label}`}
      style={{ ...ROW_STYLE, cursor: 'pointer' }}
    >
      <span style={LABEL_STYLE}>{label}</span>
      <span style={{ ...VALUE_CELL_STYLE, ...(hover ? VALUE_CELL_HOVER_STYLE : {}) }}>
        <span style={VALUE_TEXT_STYLE}>{displayLabel}</span>
        {pending && <Spinner />}
        {hover && !pending && <PencilHint />}
      </span>
    </button>
  );
}

function ToggleField({ label, value, onSave, onError, readOnly }: ToggleProps) {
  const [pending, setPending] = useState(false);
  return (
    <div style={ROW_STYLE} aria-label={label}>
      <span style={LABEL_STYLE}>{label}</span>
      <span style={{ ...VALUE_CELL_STYLE, gap: 8 }}>
        <button
          type="button"
          className="tx-toggle"
          role="switch"
          aria-checked={value}
          disabled={pending || readOnly}
          tabIndex={readOnly ? -1 : 0}
          onClick={
            readOnly
              ? undefined
              : async () => {
                  setPending(true);
                  try {
                    await onSave(!value);
                  } catch (e) {
                    onError?.(e);
                  } finally {
                    setPending(false);
                  }
                }
          }
          style={{ height: 'auto', padding: 0, flex: '0 0 auto', cursor: readOnly ? 'default' : 'pointer' }}
        >
          <span className="tx-toggle__track">
            <span className="tx-toggle__thumb" />
          </span>
        </button>
        {pending && <Spinner />}
      </span>
    </div>
  );
}
