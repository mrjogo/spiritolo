import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TasksTable } from './TasksTable';
import { batchMode } from './tasksTableModel';
import type { RunItem } from './useRunItems';

const ITEMS: RunItem[] = [
  { item_id: '1', entity_id: '1', title: 'Oaxaca Old Fashioned', source: 'diffordsguide', why_added: 'flagged', task_state: 'pending', total_count: 2 },
  { item_id: '2', entity_id: '2', title: 'Amaro Spritz', source: 'punch', why_added: 'never_run', task_state: 'pending', total_count: 2 },
];

function baseProps(overrides: Partial<React.ComponentProps<typeof TasksTable>> = {}): React.ComponentProps<typeof TasksTable> {
  return {
    runState: 'draft',
    applyMode: 'hold',
    items: ITEMS,
    total: 2,
    statusFacets: { flagged: 1, never_run: 1, failed: 0 },
    activeStatus: null,
    onStatus: vi.fn(),
    search: '',
    onSearch: vi.fn(),
    page: 1,
    pageSize: 50,
    onPage: vi.fn(),
    selectedIds: new Set<string>(),
    onSelectionChange: vi.fn(),
    onRemove: vi.fn(),
    onApply: vi.fn(),
    ...overrides,
  };
}

describe('batchMode', () => {
  it('draft → remove, done+hold → apply, running → inspect', () => {
    expect(batchMode('draft', 'hold')).toBe('remove');
    expect(batchMode('draft', 'auto')).toBe('remove');
    expect(batchMode('done', 'hold')).toBe('apply');
    expect(batchMode('done', 'auto')).toBe('inspect');
    expect(batchMode('running', 'hold')).toBe('inspect');
    expect(batchMode('queued', 'hold')).toBe('inspect');
  });
});

describe('<TasksTable> batch bar', () => {
  it('hides the batch bar with no selection', () => {
    render(<TasksTable {...baseProps()} />);
    expect(screen.queryByRole('region', { name: /task selection actions/i })).not.toBeInTheDocument();
  });

  it('draft run shows a destructive "Remove from run" action', async () => {
    const onRemove = vi.fn();
    render(<TasksTable {...baseProps({ selectedIds: new Set(['1', '2']), onRemove })} />);
    const remove = screen.getByRole('button', { name: 'Remove from run' });
    expect(remove).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Apply/ })).not.toBeInTheDocument();
    await userEvent.click(remove);
    expect(onRemove).toHaveBeenCalledWith(['1', '2']);
  });

  it('a running run is inspect-only — no Remove, no Apply', () => {
    render(<TasksTable {...baseProps({ runState: 'running', selectedIds: new Set(['1']) })} />);
    expect(screen.getByText(/inspecting/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove from run' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Apply/ })).not.toBeInTheDocument();
  });

  it('a done + hold run offers a bulk Apply', async () => {
    const onApply = vi.fn();
    render(<TasksTable {...baseProps({ runState: 'done', applyMode: 'hold', selectedIds: new Set(['1', '2']), onApply })} />);
    const apply = screen.getByRole('button', { name: /^Apply 2/ });
    await userEvent.click(apply);
    expect(onApply).toHaveBeenCalledWith(['1', '2']);
    expect(screen.queryByRole('button', { name: 'Remove from run' })).not.toBeInTheDocument();
  });

  it('renders the status chips with facet counts', () => {
    render(<TasksTable {...baseProps()} />);
    expect(screen.getByRole('button', { name: /All 2/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Flagged 1/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Never run 1/ })).toBeInTheDocument();
  });
});
