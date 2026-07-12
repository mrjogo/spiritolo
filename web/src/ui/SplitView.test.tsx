import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { SplitView, DetailPane } from './SplitView';

// Exposes the current ?sel= value from inside the router so the test can
// assert the URL was actually updated, not just that the detail re-rendered.
function SelParamProbe() {
  const [params] = useSearchParams();
  return <div data-testid="sel-probe">{params.get('sel') ?? ''}</div>;
}

describe('<SplitView>', () => {
  it('selecting a list row sets ?sel=<id> and renders the detail pane for it', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/ops/docs']}>
        <SelParamProbe />
        <SplitView
          list={({ select }) => <button onClick={() => select('42')}>Select 42</button>}
          detail={({ selectedId }) => (
            <DetailPane>{selectedId ? `Detail: ${selectedId}` : 'Nothing selected'}</DetailPane>
          )}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('Nothing selected')).toBeInTheDocument();
    expect(screen.getByTestId('sel-probe')).toHaveTextContent('');

    await user.click(screen.getByText('Select 42'));

    expect(screen.getByText('Detail: 42')).toBeInTheDocument();
    expect(screen.getByTestId('sel-probe')).toHaveTextContent('42');
  });

  it('reads the initial selection from the URL', () => {
    render(
      <MemoryRouter initialEntries={['/ops/docs?sel=7']}>
        <SplitView
          list={() => <div>list</div>}
          detail={({ selectedId }) => <DetailPane>{selectedId}</DetailPane>}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('7')).toBeInTheDocument();
  });
});
