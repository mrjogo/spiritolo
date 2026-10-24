import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SortControl } from './SortControl';

const FIELDS = [
  { col: 'last_run', label: 'Last run' },
  { col: 'title', label: 'Title' },
  { col: 'source', label: 'Source' },
];

describe('<SortControl>', () => {
  it('appends a level (asc) from the field dropdown', async () => {
    const onChange = vi.fn();
    render(
      <SortControl value={[{ col: 'last_run', asc: false }]} fields={FIELDS} onChange={onChange} />,
    );
    await userEvent.selectOptions(screen.getByLabelText('add sort field'), 'title');
    expect(onChange).toHaveBeenCalledWith([
      { col: 'last_run', asc: false },
      { col: 'title', asc: true },
    ]);
  });

  it('toggles a key direction', async () => {
    const onChange = vi.fn();
    render(<SortControl value={[{ col: 'title', asc: true }]} fields={FIELDS} onChange={onChange} />);
    await userEvent.click(screen.getByLabelText('toggle Title sort direction'));
    expect(onChange).toHaveBeenCalledWith([{ col: 'title', asc: false }]);
  });

  it('removes a key', async () => {
    const onChange = vi.fn();
    render(
      <SortControl
        value={[{ col: 'title', asc: true }, { col: 'source', asc: false }]}
        fields={FIELDS}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText('remove Source sort'));
    expect(onChange).toHaveBeenCalledWith([{ col: 'title', asc: true }]);
  });

  it('the add dropdown only offers unused fields', () => {
    render(<SortControl value={[{ col: 'title', asc: true }]} fields={FIELDS} onChange={vi.fn()} />);
    const opts = within(screen.getByLabelText('add sort field'))
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(opts).not.toContain('Title');
    expect(opts).toContain('Source');
  });
});
