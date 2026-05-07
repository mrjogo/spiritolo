import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AliasChipEditor } from './AliasChipEditor';

describe('AliasChipEditor', () => {
  it('renders chips and shows pencil on hover when not editing', async () => {
    const user = userEvent.setup();
    render(<AliasChipEditor value={['a', 'b']} onSave={vi.fn()} />);
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('b')).toBeInTheDocument();
    await user.hover(screen.getByText('a'));
    expect(screen.getByRole('button', { name: /edit aliases/i })).toBeInTheDocument();
  });

  it('add chip via Enter, remove via × — does not save until blur', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AliasChipEditor value={['a']} onSave={onSave} />);
    await user.hover(screen.getByText('a'));
    await user.click(screen.getByRole('button', { name: /edit aliases/i }));
    const input = screen.getByPlaceholderText(/add alias/i);
    await user.type(input, 'b{Enter}');
    expect(screen.getByText('b')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    await user.click(screen.getByLabelText(/remove a/i));
    expect(onSave).not.toHaveBeenCalled();
    // Move focus outside the editor to trigger blur-save
    input.blur();
    // Allow microtask to flush
    await Promise.resolve();
    expect(onSave).toHaveBeenCalledWith(['b']);
  });

  it('Esc discards staged chip changes', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<AliasChipEditor value={['a']} onSave={onSave} />);
    await user.hover(screen.getByText('a'));
    await user.click(screen.getByRole('button', { name: /edit aliases/i }));
    await user.type(screen.getByPlaceholderText(/add alias/i), 'b{Enter}');
    await user.keyboard('{Escape}');
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByText('b')).not.toBeInTheDocument();
  });
});
