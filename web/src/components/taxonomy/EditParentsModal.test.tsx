import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditParentsModal } from './EditParentsModal';
import type { TaxonomyViewRow } from './shapeData';

function row(id: number, name: string, child_ids: number[] = []): TaxonomyViewRow {
  return {
    id, slug: name.toLowerCase().replace(/ /g, '_'), display_name: name,
    node_kind: null, default_role: null,
    is_cluster_node: false, is_defining_garnish: false,
    parent_ids: [], child_ids, aliases: [], recipe_count: 0,
  };
}

const ROWS = [
  row(1, 'amari'),
  row(42, 'campari', []),
  row(84, 'bitter_aperitif'),
  row(312, 'italian_aperitif'),
  row(208, 'italian_liqueur'),
  row(319, 'italicus'),
];

const NODE = row(42, 'campari');

describe('EditParentsModal', () => {
  it('lists current parents as removable chips above the search', () => {
    render(
      <EditParentsModal
        node={NODE}
        currentParentIds={[1, 84]}
        rows={ROWS}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText('amari')).toBeInTheDocument();
    expect(screen.getByText('bitter_aperitif')).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^remove/i)).toHaveLength(2);
  });

  it('removing a parent stages the change without saving', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[1, 84]} rows={ROWS}
        onCancel={vi.fn()} onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText('remove amari'));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('result list is always visible — empty query shows all eligible nodes', () => {
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    const listbox = screen.getByRole('listbox');
    // Self ('campari', id=42) is filtered out; everything else shows up.
    expect(within(listbox).getByText('amari')).toBeInTheDocument();
    expect(within(listbox).getByText('italian_aperitif')).toBeInTheDocument();
    expect(within(listbox).queryByText('campari')).toBeNull();
  });

  it('typing filters the list; Enter on highlighted adds it', async () => {
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    await user.type(screen.getByPlaceholderText(/search/i), 'ital');
    const listbox = screen.getByRole('listbox');
    expect(within(listbox).getByText('italian_liqueur')).toBeInTheDocument();
    expect(within(listbox).getByText('italicus')).toBeInTheDocument();
    expect(within(listbox).queryByText('amari')).toBeNull();
    await user.keyboard('{Enter}');
    // First alphabetical match (italian_aperitif) is added as a chip; once
    // selected, it disappears from the list.
    expect(screen.getByLabelText(/remove italian_aperitif/i)).toBeInTheDocument();
  });

  it('hides descendants of the current node from the list (no cycles)', () => {
    // Make 312 a child of 42: 42 → 312
    const rowsWithDescendant = [
      ...ROWS.filter((r) => r.id !== 42),
      { ...NODE, child_ids: [312] },
    ];
    render(
      <EditParentsModal
        node={{ ...NODE, child_ids: [312] }}
        currentParentIds={[]}
        rows={rowsWithDescendant}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const listbox = screen.getByRole('listbox');
    expect(within(listbox).queryByText('italian_aperitif')).toBeNull();
  });

  it('clicking a list row adds it as a chip', async () => {
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    const listbox = screen.getByRole('listbox');
    await user.click(within(listbox).getByText('italian_liqueur'));
    expect(screen.getByLabelText(/remove italian_liqueur/i)).toBeInTheDocument();
  });

  it('Save calls onSave with the current selection', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[1, 84]} rows={ROWS}
        onCancel={vi.fn()} onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText('remove amari'));
    const listbox = screen.getByRole('listbox');
    await user.click(within(listbox).getByText('italian_liqueur'));
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(42, expect.arrayContaining([84, 208]));
    expect(onSave.mock.calls[0][1]).not.toContain(1);
  });

  it('Save button is disabled when there are no changes', () => {
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[1, 84]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
  });

  it('"none" placeholder shows when nothing is selected', () => {
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    expect(screen.getByText(/^none$/i)).toBeInTheDocument();
  });
});
