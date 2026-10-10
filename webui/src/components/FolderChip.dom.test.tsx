import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { FolderIndicatorChip } from './FolderChip';

describe('FolderIndicatorChip component', () => {
  it('renders with .folder-indicator-chip and .folder-color-dot without inline dimension styles', () => {
    const { container } = render(
      <FolderIndicatorChip folder={{ name: 'Neurologia', color: '#4a729c' }} />,
    );

    const chip = container.querySelector('.folder-indicator-chip') as HTMLElement;
    expect(chip).toBeTruthy();
    expect(chip.getAttribute('style')).toContain('--folder-color: #4a729c');
    expect(screen.getByText('Neurologia')).toBeTruthy();

    const dot = container.querySelector('.folder-color-dot.is-small') as HTMLElement;
    expect(dot).toBeTruthy();
    // Verify no inline width/height style is present
    expect(dot.getAttribute('style')).toBeNull();
  });

  it('falls back to DEFAULT_FOLDER_COLOR when folder color is missing or empty', () => {
    const { container } = render(
      <FolderIndicatorChip folder={{ name: 'Senza Colore', color: '' }} />,
    );

    const chip = container.querySelector('.folder-indicator-chip') as HTMLElement;
    expect(chip).toBeTruthy();
    expect(chip.getAttribute('style')).toContain('--folder-color: #FF6B6B');
    expect(screen.getByText('Senza Colore')).toBeTruthy();
  });
});
