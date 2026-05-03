import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AppLayout } from './AppLayout';

vi.mock('./Header', () => ({ Header: () => <header>mock-header</header> }));

describe('AppLayout', () => {
  it('renders Header and the matched child route via Outlet', () => {
    render(
      <MemoryRouter initialEntries={['/recipes']}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/recipes" element={<div>child-page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('mock-header')).toBeInTheDocument();
    expect(screen.getByText('child-page')).toBeInTheDocument();
  });
});
