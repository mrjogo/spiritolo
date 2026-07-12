import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DataTable } from './DataTable';
import { StatusPill } from './StatusPill';

type Row = { id: number; name: string; state: string };

const rows: Row[] = [
  { id: 1, name: 'Old Fashioned', state: 'resolved' },
  { id: 2, name: 'Negroni', state: 'pending' },
];

describe('<DataTable>', () => {
  it('renders columns, custom-rendered cells, a sticky header, and an overflow-x wrapper', () => {
    const { container } = render(
      <DataTable<Row>
        columns={[
          { key: 'name', header: 'Name' },
          { key: 'state', header: 'State', render: (r) => <StatusPill kind={r.state} /> },
        ]}
        rows={rows}
        rowKey={(r) => r.id}
      />,
    );
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'State' })).toBeInTheDocument();
    expect(screen.getByText('Old Fashioned')).toBeInTheDocument();
    expect(screen.getByText('resolved')).toBeInTheDocument();

    const thead = container.querySelector('thead') as HTMLElement;
    expect(thead.style.position).toBe('sticky');

    const wrapper = container.querySelector('.data-table__wrapper') as HTMLElement;
    expect(wrapper.style.overflowX).toBe('auto');
  });

  it('selectable table: clicking a row checkbox calls onSelectionChange with the selected ids', async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <DataTable<Row>
        columns={[{ key: 'name', header: 'Name' }]}
        rows={rows}
        rowKey={(r) => r.id}
        selectable
        onSelectionChange={onSelectionChange}
      />,
    );
    await user.click(screen.getByRole('checkbox', { name: /select row 1/i }));
    expect(onSelectionChange).toHaveBeenCalledWith([1]);
  });

  it('onRowClick fires with the row on click, and is keyboard-accessible', async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <DataTable<Row>
        columns={[{ key: 'name', header: 'Name' }]}
        rows={rows}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />,
    );
    const row = screen.getByRole('button', { name: /old fashioned/i });
    await user.click(row);
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);

    row.focus();
    await user.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenCalledTimes(2);
    expect(onRowClick).toHaveBeenLastCalledWith(rows[0]);
  });
});
