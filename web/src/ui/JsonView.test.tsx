import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JsonView } from './JsonView';

describe('<JsonView>', () => {
  it('renders a leaf value directly', () => {
    render(<JsonView value="hello" />);
    expect(screen.getByText('"hello"')).toBeInTheDocument();
  });

  it('renders a nested object collapsed, and expands its children on click', async () => {
    const user = userEvent.setup();
    render(<JsonView value={{ a: 1, nested: { b: 2 } }} />);

    // The root object is expanded by default (depth 0) so its top-level
    // keys are visible…
    expect(screen.getByText(/a:/)).toBeInTheDocument();
    // …but the nested object is collapsed — its own children aren't shown.
    expect(screen.queryByText(/b:/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /toggle nested/i }));
    expect(screen.getByText(/b:/)).toBeInTheDocument();
  });

  it('renders arrays with numeric indices', () => {
    render(<JsonView value={['x', 'y']} />);
    expect(screen.getByText(/Array\(2\)/)).toBeInTheDocument();
  });

  it('is read-only — renders no input/textarea elements', () => {
    const { container } = render(<JsonView value={{ a: { b: { c: 1 } } }} />);
    expect(container.querySelectorAll('input, textarea')).toHaveLength(0);
  });

  it('renders null and booleans as leaves without throwing', () => {
    expect(() =>
      render(<JsonView value={{ isNull: null, isTrue: true }} />),
    ).not.toThrow();
    expect(screen.getByText('null')).toBeInTheDocument();
    expect(screen.getByText('true')).toBeInTheDocument();
  });
});
