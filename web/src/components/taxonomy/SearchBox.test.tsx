import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchBox } from './SearchBox';

describe('<SearchBox>', () => {
  it('emits onChange as the user types', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SearchBox value="" onChange={onChange} onSubmit={() => {}} />);
    await user.type(screen.getByRole('textbox'), 'rye');
    expect(onChange).toHaveBeenLastCalledWith('rye');
  });

  it('emits onSubmit on Enter', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<SearchBox value="rye" onChange={() => {}} onSubmit={onSubmit} />);
    await user.type(screen.getByRole('textbox'), '{Enter}');
    expect(onSubmit).toHaveBeenCalled();
  });
});
