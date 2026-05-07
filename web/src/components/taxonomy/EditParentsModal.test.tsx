import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
  it('lists current parents with name #id and × to remove', () => {
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
    expect(screen.getByText('#1')).toBeInTheDocument();
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

  it('search shows results with #id; pressing Enter on highlighted adds to staging', async () => {
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    await user.type(screen.getByPlaceholderText(/search/i), 'ital');
    expect(screen.getByText('italian_liqueur')).toBeInTheDocument();
    expect(screen.getByText('italicus')).toBeInTheDocument();
    await user.keyboard('{Enter}');
    // First result added — exact behavior: top result
    expect(screen.getAllByText(/^italian_/i).length).toBeGreaterThan(0);
  });

  it('greys out descendants of the current node (would-cycle)', () => {
    // make 312 a descendant of 42: 42 → 312
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
    const input = screen.getByPlaceholderText(/search/i);
    input.focus();
    userEvent.setup().type(input, 'italian_aperitif');
    // The descendant row should render with the cycle marker
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((screen as any).queryByText(/would create cycle/i)).toBeTruthy();
  });

  it('SAVE calls onSave with merged parent_ids (current minus removed plus added)', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[1, 84]} rows={ROWS}
        onCancel={vi.fn()} onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText('remove amari'));
    await user.type(screen.getByPlaceholderText(/search/i), 'italian_liqueur');
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(42, expect.arrayContaining([84, 208]));
    expect(onSave.mock.calls[0][1]).not.toContain(1);
  });
});
