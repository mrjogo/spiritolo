import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { flagFormSchema, type FlagFormInput } from './schemas';

interface Props {
  existingReasons: string[];
  onSubmit: (reason: string) => Promise<void> | void;
  onCancel: () => void;
}

export function FlagInput({ existingReasons, onSubmit, onCancel }: Props) {
  const form = useForm<FlagFormInput>({
    resolver: zodResolver(flagFormSchema),
    defaultValues: { reason: '' },
  });

  return (
    <form
      onSubmit={form.handleSubmit(async (v) => {
        await onSubmit(v.reason.trim());
      })}
    >
      <label htmlFor="flag-reason" className="tx-field__label">Flag reason</label>
      <input
        id="flag-reason"
        type="text"
        className="tx-input"
        list="flag-reasons-list"
        autoFocus
        aria-invalid={!!form.formState.errors.reason || undefined}
        {...form.register('reason')}
      />
      <datalist id="flag-reasons-list">
        {existingReasons.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
      {form.formState.errors.reason && (
        <div className="tx-field__error">{form.formState.errors.reason.message}</div>
      )}
      <div className="tx-form-actions" style={{ marginTop: 8 }}>
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
          Save flag
        </button>
      </div>
    </form>
  );
}
