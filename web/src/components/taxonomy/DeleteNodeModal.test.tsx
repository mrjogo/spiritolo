import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeleteNodeModal } from './DeleteNodeModal';

const NODE = { id: 42, slug: 'campari', display_name: 'Campari' };

describe('DeleteNodeModal', () => {
  it('shows loading state, then no-blocker form when fetchBlockers resolves clean', async () => {
    const fetchBlockers = vi.fn().mockResolvedValue({
      children: 0, child_names: [], parents: 2, aliases: 1, provenance: 1,
      recipe_ingredients: 0, taxonomy_proposals: 0,
    });
    render(
      <DeleteNodeModal node={NODE} fetchBlockers={fetchBlockers} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText(/Delete Campari/i)).toBeInTheDocument());
    expect(screen.getByText(/Type slug to confirm/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeDisabled();
  });

  it('disables DELETE button when blockers exist; surfaces blocker list', async () => {
    const fetchBlockers = vi.fn().mockResolvedValue({
      children: 3, child_names: [
        { id: 118, display_name: 'gin_campari' },
        { id: 127, display_name: 'aperol_campari_blend' },
        { id: 200, display_name: 'other' },
      ],
      parents: 2, aliases: 1, provenance: 1,
      recipe_ingredients: 12, taxonomy_proposals: 0,
    });
    render(
      <DeleteNodeModal node={NODE} fetchBlockers={fetchBlockers} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText(/3 children/i)).toBeInTheDocument());
    expect(screen.getByText(/12 recipe_ingredients references/i)).toBeInTheDocument();
    expect(screen.queryByText(/Type slug to confirm/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeDisabled();
  });

  it('enables DELETE only when typed slug matches', async () => {
    const fetchBlockers = vi.fn().mockResolvedValue({
      children: 0, child_names: [], parents: 0, aliases: 0, provenance: 0,
      recipe_ingredients: 0, taxonomy_proposals: 0,
    });
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <DeleteNodeModal node={NODE} fetchBlockers={fetchBlockers} onCancel={vi.fn()} onConfirm={onConfirm} />,
    );
    await waitFor(() => expect(screen.getByLabelText(/confirm slug/i)).toBeInTheDocument());
    const del = screen.getByRole('button', { name: /^delete$/i });
    expect(del).toBeDisabled();
    await user.type(screen.getByLabelText(/confirm slug/i), 'campari');
    expect(del).not.toBeDisabled();
    await user.click(del);
    expect(onConfirm).toHaveBeenCalledWith(42);
  });
});
