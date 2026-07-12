/// <reference types="node" />
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { EditableField } from './EditableField';

// vitest.config has `test.css: false` (imported .css files are stubbed, not
// injected into jsdom, and — unlike a plain browser build — this also
// swallows Vite's `?raw` suffix for .css specifically) so we read the REAL
// tokens.css off disk via node:fs and inject it as an actual <style> tag.
// This exercises the shipped CSS text itself, rather than a hand-copied
// duplicate, and would fail if tokens.css's selectors regressed back to
// being scoped under .taxonomy-page.
const here = dirname(fileURLToPath(import.meta.url));
const tokensCss = readFileSync(resolve(here, './tokens.css'), 'utf8');

let styleEl: HTMLStyleElement | null = null;

function injectRealTokensCss() {
  styleEl = document.createElement('style');
  styleEl.textContent = tokensCss;
  document.head.appendChild(styleEl);
}

afterEach(() => {
  styleEl?.remove();
  styleEl = null;
});

describe('ui/tokens.css', () => {
  it('resolves --tx-form-border for an EditableField rendered OUTSIDE any .taxonomy-page ancestor', () => {
    injectRealTokensCss();
    render(<EditableField label="X" kind="text" value="hello" onSave={() => {}} />);
    const row = screen.getByText('hello').closest('[aria-label]') as HTMLElement;
    expect(row).toBeTruthy();
    const resolved = getComputedStyle(row).getPropertyValue('--tx-form-border').trim();
    expect(resolved).not.toBe('');
  });

  it('resolves --st-resolved and --job-running to non-empty semantic colors under .ops', () => {
    injectRealTokensCss();
    const { container } = render(<div className="ops"><div id="probe" /></div>);
    const probe = container.querySelector('#probe') as HTMLElement;
    const resolvedOutcome = getComputedStyle(probe).getPropertyValue('--st-resolved').trim();
    const resolvedJob = getComputedStyle(probe).getPropertyValue('--job-running').trim();
    expect(resolvedOutcome).not.toBe('');
    expect(resolvedJob).not.toBe('');
  });
});
