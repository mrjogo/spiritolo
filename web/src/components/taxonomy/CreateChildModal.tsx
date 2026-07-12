import { useEffect, useRef } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  createChildSchema, deriveSlug,
  NODE_KIND_OPTIONS, DEFAULT_ROLE_OPTIONS,
  type CreateChildInput,
} from './schemas';
import { AliasChipEditor } from './AliasChipEditor';
import { ModalShell } from '../../ui/Modal';

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
        <Field label="Display name *" error={form.formState.errors.display_name?.message}>
          <input
            id="dn"
            className="tx-input"
            aria-label="display name"
            aria-invalid={!!form.formState.errors.display_name || undefined}
            {...form.register('display_name')}
          />
        </Field>
        <Field label="Slug *" error={form.formState.errors.slug?.message}>
          <input
            id="slug"
            className="tx-input"
            aria-label="slug"
            aria-invalid={!!form.formState.errors.slug || undefined}
            {...form.register('slug', {
              onChange: () => { slugTouchedRef.current = true; },
            })}
          />
        </Field>
        <div className="tx-form-row">
          <Field label="Node kind">
            <Controller
              control={form.control}
              name="node_kind"
              render={({ field }) => (
                <select
                  className="tx-select"
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
          <Field label="Default role">
            <Controller
              control={form.control}
              name="default_role"
              render={({ field }) => (
                <select
                  className="tx-select"
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
        <div className="tx-toggle-row">
          <ToggleControl name="is_cluster_node" label="cluster" form={form} />
          <ToggleControl name="is_defining_garnish" label="garnish" form={form} />
        </div>
        <Field label="Aliases">
          <Controller
            control={form.control}
            name="aliases"
            render={({ field }) => (
              <AliasChipEditor
                alwaysEdit
                value={field.value}
                onSave={(v) => { field.onChange(v); }}
              />
            )}
          />
        </Field>
        <div className="tx-form-actions">
          <button
            type="button"
            className="tx-btn tx-btn--ghost"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="tx-btn tx-btn--primary"
            disabled={form.formState.isSubmitting}
          >
            Create
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function Field({
  label, error, children,
}: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="tx-field">
      <label className="tx-field__label">{label}</label>
      {children}
      {error && <div className="tx-field__error">{error}</div>}
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
      className="tx-toggle"
      role="switch"
      aria-checked={value}
      aria-label={label}
      onClick={() => form.setValue(name, !value)}
    >
      <span className="tx-toggle__track">
        <span className="tx-toggle__thumb" />
      </span>
      <span>{label}</span>
    </button>
  );
}

