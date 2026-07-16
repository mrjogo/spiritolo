import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditableField } from './EditableField';

describe('EditableField — text', () => {
  it('shows pencil on hover and value when not editing', async () => {
    const user = userEvent.setup();
    render(
      <EditableField
        label="DISPLAY NAME"
        kind="text"
        value="Campari"
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText('Campari')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.hover(screen.getByText('Campari'));
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument();
  });

  it('opens textbox on pencil click, prefilled with value', async () => {
    const user = userEvent.setup();
    render(<EditableField label="X" kind="text" value="hello" onSave={vi.fn()} />);
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    const input = screen.getByRole('textbox') as HTMLInputElement;
    expect(input.value).toBe('hello');
  });

  it('Enter calls onSave with new value, then exits edit mode', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<EditableField label="X" kind="text" value="hello" onSave={onSave} />);
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    const input = screen.getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'world{Enter}');
    expect(onSave).toHaveBeenCalledWith('world');
  });

  it('Esc cancels and reverts', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<EditableField label="X" kind="text" value="hello" onSave={onSave} />);
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    const input = screen.getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'world');
    await user.keyboard('{Escape}');
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('reverts and surfaces error if onSave rejects', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('boom'));
    const onError = vi.fn();
    const user = userEvent.setup();
    render(
      <EditableField label="X" kind="text" value="hello" onSave={onSave} onError={onError} />,
    );
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    await user.clear(screen.getByRole('textbox'));
    await user.type(screen.getByRole('textbox'), 'world{Enter}');
    expect(onError).toHaveBeenCalled();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });
});

describe('EditableField — dropdown', () => {
  it('selecting an option commits immediately', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditableField
        label="NODE KIND"
        kind="dropdown"
        value="brand"
        options={[
          { value: '', label: '(none)' },
          { value: 'brand', label: 'brand' },
          { value: 'expression', label: 'expression' },
        ]}
        onSave={onSave}
      />,
    );
    await user.hover(screen.getByText('brand'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    await user.selectOptions(screen.getByRole('combobox'), 'expression');
    expect(onSave).toHaveBeenCalledWith('expression');
  });
});

describe('EditableField — toggle', () => {
  it('clicking the toggle commits the new boolean immediately', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditableField
        label="CLUSTER"
        kind="toggle"
        value={false}
        onSave={onSave}
      />,
    );
    await user.click(screen.getByRole('switch'));
    expect(onSave).toHaveBeenCalledWith(true);
  });
});
