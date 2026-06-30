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
  it('renders raw lines as a plain list for non-admins', () => {
    renderIt({
      rawLines: ['2 oz gin', '1 oz lime juice'],
      parsedByPosition: null,
    });
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('2 oz gin')).toBeInTheDocument();
    expect(within(items[1]).getByText('1 oz lime juice')).toBeInTheDocument();
    // No parsed cards rendered for non-admins.
    expect(screen.queryByText(/^#/)).toBeNull();
  });

  it('renders raw line + parsed squircle aligned per row for admins', () => {
    const rows = [
      row({ position: 0, raw_text: '2 oz gin', amount: 2, unit: 'oz', name: 'gin', taxonomy_node_id: 5, taxonomy_nodes: { slug: 'gin', display_name: 'Gin' }, role: 'base_spirit', id: 17 }),
      row({ position: 1, raw_text: '1 oz fresh lime juice', amount: 1, unit: 'oz', name: 'lime juice', modifier: 'fresh', taxonomy_node_id: 9, taxonomy_nodes: { slug: 'lime-juice', display_name: 'Lime Juice' }, role: 'citrus', id: 18 }),
    ];
    renderIt({
      rawLines: ['2 oz gin', '1 oz fresh lime juice'],
      parsedByPosition: asMap(rows),
    });
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);

    const first = within(items[0]);
    expect(first.getByText('2 oz gin')).toBeInTheDocument();
    expect(first.getByText('#17')).toBeInTheDocument();
    expect(first.getByText('2 oz')).toBeInTheDocument();
    expect(first.getByRole('link', { name: /gin/i })).toHaveAttribute('href', '/taxonomy?node=gin');
    expect(first.getByText('base_spirit')).toBeInTheDocument();

    const second = within(items[1]);
    expect(second.getByText('1 oz fresh lime juice')).toBeInTheDocument();
    expect(second.getByText('#18')).toBeInTheDocument();
    expect(second.getByText('1 oz')).toBeInTheDocument();
    expect(second.getByText('fresh')).toBeInTheDocument();
    expect(second.getByText('citrus')).toBeInTheDocument();
    expect(second.getByRole('link', { name: /lime juice/i })).toHaveAttribute('href', '/taxonomy?node=lime-juice');
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

  it('renders an unparseable row inside a tinted squircle', () => {
    const r = row({
      position: 0, parse_status: 'unparseable',
      amount: null, unit: null, name: null,
      taxonomy_node_id: null, taxonomy_nodes: null, role: null,
    });
    renderIt({ rawLines: ['Sweet vermouth (your favorite)'], parsedByPosition: asMap([r]) });
    expect(screen.getByText(/unparseable/i)).toBeInTheDocument();
    expect(screen.getByText('Sweet vermouth (your favorite)')).toBeInTheDocument();
  });

  it('renders unmapped row with name as plain text and no link', () => {
    const r = row({
      position: 0, name: 'lemon',
      taxonomy_node_id: null, taxonomy_nodes: null, role: 'garnish',
    });
    renderIt({ rawLines: ['Garnish: lemon twist'], parsedByPosition: asMap([r]) });
    expect(screen.queryByRole('link', { name: /lemon/i })).toBeNull();
    expect(screen.getByText('lemon')).toBeInTheDocument();
    expect(screen.getByText('garnish')).toBeInTheDocument();
  });

  it('renders "not parsed" squircle for raw lines with no parsed row', () => {
    renderIt({
      rawLines: ['2 oz gin', '1 oz lime'],
      parsedByPosition: asMap([row({ position: 0, raw_text: '2 oz gin' })]),
    });
    expect(screen.getByText(/not parsed/i)).toBeInTheDocument();
  });
});
