import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ErrorPage } from './ErrorPage';

function renderAt(title: string, message: string) {
  return render(
    <MemoryRouter>
      <ErrorPage title={title} message={message} />
    </MemoryRouter>,
  );
}

describe('<ErrorPage>', () => {
  it('renders the title as a heading', () => {
    renderAt('Page not found', 'Nothing here.');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('renders the message', () => {
    renderAt('Page not found', 'Nothing here.');
    expect(screen.getByText('Nothing here.')).toBeInTheDocument();
  });

  it('has a link back to /', () => {
    renderAt('Page not found', 'Nothing here.');
    const link = screen.getByRole('link', { name: /back to recipes/i });
    expect(link).toHaveAttribute('href', '/');
  });
});
