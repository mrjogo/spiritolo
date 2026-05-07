import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { StructuredIngredients } from './StructuredIngredients';
import type { RecipeIngredientRow } from '../../types';

function row(over: Partial<RecipeIngredientRow> = {}): RecipeIngredientRow {
  return {
    id: 100, position: 0, raw_text: '2 oz gin',
    amount: 2, amount_max: null, unit: 'oz',
    name: 'gin', modifier: null,
    role: 'base_spirit', parse_status: 'parsed',
    taxonomy_node_id: 5,
    taxonomy_nodes: { slug: 'gin', display_name: 'Gin' },
    ...over,
  };
}

function asMap(rows: RecipeIngredientRow[]): Map<number, RecipeIngredientRow> {
  return new Map(rows.map((r) => [r.position, r]));
}

function renderIt(props: React.ComponentProps<typeof StructuredIngredients>) {
  return render(
    <MemoryRouter>
      <StructuredIngredients {...props} />
    </MemoryRouter>,
  );
}

describe('<StructuredIngredients>', () => {
  it('renders raw lines as a single-column table for non-admins', () => {
    renderIt({
      rawLines: ['2 oz gin', '1 oz lime juice'],
      parsedByPosition: null,
    });
    const rows = screen.getAllByRole('row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('2 oz gin')).toBeInTheDocument();
    expect(within(rows[1]).getByText('1 oz lime juice')).toBeInTheDocument();
    const cells0 = within(rows[0]).getAllByRole('cell');
    expect(cells0).toHaveLength(1);
  });

  it('renders aligned cells for admin happy path', () => {
    const rows = [
      row({ position: 0, raw_text: '2 oz gin', amount: 2, unit: 'oz', name: 'gin', taxonomy_node_id: 5, taxonomy_nodes: { slug: 'gin', display_name: 'Gin' }, role: 'base_spirit', id: 17 }),
      row({ position: 1, raw_text: '1 oz fresh lime juice', amount: 1, unit: 'oz', name: 'lime juice', modifier: 'fresh', taxonomy_node_id: 9, taxonomy_nodes: { slug: 'lime_juice', display_name: 'Lime Juice' }, role: 'citrus', id: 18 }),
    ];
    renderIt({
      rawLines: ['2 oz gin', '1 oz fresh lime juice'],
      parsedByPosition: asMap(rows),
    });
    const tableRows = screen.getAllByRole('row');
    expect(tableRows).toHaveLength(3); // 1 header + 2 data
    const r0 = within(tableRows[1]);
    expect(r0.getByText('2 oz gin')).toBeInTheDocument();
    expect(r0.getByText('2 oz')).toBeInTheDocument();
    expect(r0.getByRole('link', { name: /gin/i })).toHaveAttribute('href', '/taxonomy?node=gin');
    expect(r0.getByText('base_spirit')).toBeInTheDocument();
    expect(r0.getByText('17')).toBeInTheDocument();

    const r1 = within(tableRows[2]);
    expect(r1.getByText('1 oz')).toBeInTheDocument();
    expect(r1.getByText('fresh')).toBeInTheDocument();
    expect(r1.getByText('citrus')).toBeInTheDocument();
    expect(r1.getByRole('link', { name: /lime juice/i })).toHaveAttribute('href', '/taxonomy?node=lime_juice');
    expect(r1.getByText('18')).toBeInTheDocument();
  });

  it('renders amount ranges as "min–max unit"', () => {
    const r = row({ amount: 1, amount_max: 2, unit: 'oz' });
    renderIt({ rawLines: ['…'], parsedByPosition: asMap([r]) });
    expect(screen.getByText('1–2 oz')).toBeInTheDocument();
  });

  it('renders amount with no unit as bare number', () => {
    const r = row({ amount: 3, amount_max: null, unit: null });
    renderIt({ rawLines: ['…'], parsedByPosition: asMap([r]) });
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders an unparseable row with collapsed right-side cell', () => {
    const r = row({
      position: 0, parse_status: 'unparseable',
      amount: null, unit: null, name: null,
      taxonomy_node_id: null, taxonomy_nodes: null, role: null,
    });
    renderIt({ rawLines: ['Sweet vermouth (your favorite)'], parsedByPosition: asMap([r]) });
    expect(screen.getByText(/unparseable/i)).toBeInTheDocument();
    expect(screen.getByText('Sweet vermouth (your favorite)')).toBeInTheDocument();
  });

  it('renders unmapped row with name as plain text and an unmapped chip', () => {
    const r = row({
      position: 0, name: 'lemon',
      taxonomy_node_id: null, taxonomy_nodes: null, role: 'garnish',
    });
    renderIt({ rawLines: ['Garnish: lemon twist'], parsedByPosition: asMap([r]) });
    expect(screen.queryByRole('link', { name: /lemon/i })).toBeNull();
    expect(screen.getByText('lemon')).toBeInTheDocument();
    expect(screen.getByText(/unmapped/i)).toBeInTheDocument();
    expect(screen.getByText('garnish')).toBeInTheDocument();
  });

  it('renders "not parsed" for raw lines with no parsed row', () => {
    renderIt({
      rawLines: ['2 oz gin', '1 oz lime'],
      parsedByPosition: asMap([row({ position: 0, raw_text: '2 oz gin' })]),
    });
    expect(screen.getByText(/not parsed/i)).toBeInTheDocument();
  });
});
