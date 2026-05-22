import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FlagInput } from './FlagInput';

describe('<FlagInput>', () => {
  it('submits the typed reason', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <FlagInput
        existingReasons={['needs more research']}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/flag reason/i), 'syrup vs liqueur?');
    await user.click(screen.getByRole('button', { name: /save flag/i }));
    expect(onSubmit).toHaveBeenCalledWith('syrup vs liqueur?');
  });

  it('blocks submission when reason is empty', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(
      <FlagInput existingReasons={[]} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await user.click(screen.getByRole('button', { name: /save flag/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/reason required/i)).toBeInTheDocument();
  });

  it('lists existing reasons in the datalist for autocomplete', () => {
    render(
      <FlagInput
        existingReasons={['needs research', 'split required']}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const options = screen.getAllByRole('option', { hidden: true })
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(['needs research', 'split required']);
  });

  it('Cancel calls onCancel', async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<FlagInput existingReasons={[]} onSubmit={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });
});
