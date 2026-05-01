import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Header } from './Header';

describe('<Header>', () => {
  it('renders the SPIRITOLO wordmark', () => {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );
    expect(screen.getByText(/spiritolo/i)).toBeInTheDocument();
  });

  it('links to / and /taxonomy', () => {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /recipes/i })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: /taxonomy/i })).toHaveAttribute('href', '/taxonomy');
  });
});
