import { useEffect, useRef } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  createChildSchema, deriveSlug,
  NODE_KIND_OPTIONS, DEFAULT_ROLE_OPTIONS,
  type CreateChildInput,
} from './schemas';
import { AliasChipEditor } from './AliasChipEditor';

interface Props {
  parent: { id: number; display_name: string };
  onCancel: () => void;
  onCreate: (parentId: number, input: CreateChildInput) => Promise<void> | void;
}

export function CreateChildModal({ parent, onCancel, onCreate }: Props) {
  const slugTouchedRef = useRef(false);

  const form = useForm<CreateChildInput>({
    resolver: zodResolver(createChildSchema),
    defaultValues: {
      display_name: '',
      slug: '',
      node_kind: null,
      default_role: null,
      is_cluster_node: false,
      is_defining_garnish: false,
      aliases: [],
    },
  });

  const dn = form.watch('display_name');
  useEffect(() => {
    if (slugTouchedRef.current) return;
    const derived = deriveSlug(dn);
    const current = form.getValues('slug');
    // Only call setValue when value actually changes; avoids triggering
    // the slug field's onChange (which would mark slugTouchedRef = true).
    if (derived !== current) {
      form.setValue('slug', derived, { shouldValidate: false });
    }
  }, [dn, form]);

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">New child of {parent.display_name}</h2>
      <div className="tx-modal__subtitle">PARENT · {parent.display_name} (#{parent.id})</div>
      <form onSubmit={form.handleSubmit((v) => onCreate(parent.id, v))}>
        <Field label="DISPLAY NAME *" error={form.formState.errors.display_name?.message}>
          <input
            id="dn"
            aria-label="display name"
            {...form.register('display_name')}
          />
        </Field>
        <Field label="SLUG *" error={form.formState.errors.slug?.message}>
          <input
            id="slug"
            aria-label="slug"
            {...form.register('slug', {
              onChange: () => { slugTouchedRef.current = true; },
            })}
          />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <Field label="NODE KIND">
            <Controller
              control={form.control}
              name="node_kind"
              render={({ field }) => (
                <select
                  aria-label="node kind"
                  value={field.value ?? ''}
                  onChange={(e) => field.onChange(e.target.value === '' ? null : e.target.value)}
                >
                  <option value="">(none)</option>
                  {NODE_KIND_OPTIONS.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              )}
            />
          </Field>
          <Field label="DEFAULT ROLE">
            <Controller
              control={form.control}
              name="default_role"
              render={({ field }) => (
                <select
                  aria-label="default role"
                  value={field.value ?? ''}
                  onChange={(e) => field.onChange(e.target.value === '' ? null : e.target.value)}
                >
                  <option value="">(none)</option>
                  {DEFAULT_ROLE_OPTIONS.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              )}
            />
          </Field>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 8 }}>
          <ToggleControl name="is_cluster_node" label="cluster" form={form} />
          <ToggleControl name="is_defining_garnish" label="garnish" form={form} />
        </div>
        <Field label="ALIASES">
          <Controller
            control={form.control}
            name="aliases"
            render={({ field }) => (
              <AliasChipEditor
                value={field.value}
                onSave={(v) => { field.onChange(v); }}
              />
            )}
          />
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button type="button" onClick={onCancel}>CANCEL</button>
          <button type="submit" disabled={form.formState.isSubmitting}>CREATE</button>
        </div>
      </form>
    </ModalShell>
  );
}

function Field({
  label, error, children,
}: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <label className="tx-modal__label">{label}</label>
      {children}
      {error && <div className="tx-modal__error">{error}</div>}
    </div>
  );
}

function ToggleControl({
  form, name, label,
}: {
  form: ReturnType<typeof useForm<CreateChildInput>>;
  name: 'is_cluster_node' | 'is_defining_garnish';
  label: string;
}) {
  const value = form.watch(name);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={label}
      onClick={() => form.setValue(name, !value)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: 'transparent', border: 'none', cursor: 'pointer',
      }}
    >
      <span style={{
        width: 28, height: 14, borderRadius: 7, position: 'relative',
        background: value ? '#b8924d' : '#d4c8a8',
      }}>
        <span style={{
          position: 'absolute', left: value ? 14 : 1, top: 1,
          width: 12, height: 12, borderRadius: '50%', background: 'white',
        }} />
      </span>
      <span style={{ fontFamily: "'Cinzel', serif", fontSize: 10 }}>{label}</span>
    </button>
  );
}

export function ModalShell({
  onBackdropClick, children,
}: { onBackdropClick: () => void; children: React.ReactNode }) {
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
