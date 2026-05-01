import { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchBox } from './SearchBox';

function Harness({
  onChange,
  onSubmit,
  initial = '',
}: {
  onChange?: (v: string) => void;
  onSubmit?: () => void;
  initial?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <SearchBox
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
      onSubmit={onSubmit ?? (() => {})}
    />
  );
}

describe('<SearchBox>', () => {
  it('emits onChange as the user types', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await user.type(screen.getByRole('textbox'), 'rye');
    expect(onChange).toHaveBeenLastCalledWith('rye');
  });

  it('emits onSubmit on Enter', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness initial="rye" onSubmit={onSubmit} />);
    await user.type(screen.getByRole('textbox'), '{Enter}');
    expect(onSubmit).toHaveBeenCalled();
  });
});
