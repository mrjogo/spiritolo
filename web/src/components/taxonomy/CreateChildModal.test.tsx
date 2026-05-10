import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreateChildModal } from './CreateChildModal';

const parent = { id: 42, display_name: 'Campari' };

describe('CreateChildModal', () => {
  it('renders title with parent name and id', () => {
    render(
      <CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={vi.fn()} />,
    );
    expect(screen.getByText(/New child of Campari/i)).toBeInTheDocument();
    expect(screen.getByText(/#42/)).toBeInTheDocument();
  });

  it('auto-derives slug from display_name until slug is touched', async () => {
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={vi.fn()} />);
    const dn = screen.getByLabelText(/display name/i);
    await user.type(dn, 'Aperol Spritz');
    const slug = screen.getByLabelText(/^slug/i) as HTMLInputElement;
    expect(slug.value).toBe('aperol-spritz');
    // Touch the slug — auto-derive should stop.
    await user.clear(slug);
    await user.type(slug, 'aperol-spritz-v2');
    await user.clear(dn);
    await user.type(dn, 'Other Name');
    expect(slug.value).toBe('aperol-spritz-v2');
  });

  it('rejects empty display_name', async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={onCreate} />);
    await user.click(screen.getByRole('button', { name: /create/i }));
    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByText(/display name required/i)).toBeInTheDocument();
  });

  it('CREATE calls onCreate with the form payload and parent id', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={onCreate} />);
    await user.type(screen.getByLabelText(/display name/i), 'Negroni');
    await user.click(screen.getByRole('button', { name: /create/i }));
    expect(onCreate).toHaveBeenCalledWith(42, expect.objectContaining({
      display_name: 'Negroni',
      slug: 'negroni',
      node_kind: null,
      default_role: null,
      is_cluster_node: false,
      is_defining_garnish: false,
      aliases: [],
    }));
  });

  it('CANCEL calls onCancel', async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={onCancel} onCreate={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });
});
